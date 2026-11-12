"""Behavioral checks for tool execution, visibility, bounds and budget failures."""

import asyncio
import json
from types import SimpleNamespace

import numpy as np
import pytest
from inspect_ai.model import ModelOutput, ModelUsage

from soc_triage.agent import LiveInspectAdapter, RecordedAdapter, run_agent, run_recorded
from soc_triage.retrieval import LocalRunbookIndex, Runbook
from soc_triage.schema import Alert, parse_decision
from soc_triage.tools import ToolEnvironment


class Encoder:
    def encode(self, sentences):
        return np.ones((len(sentences), 2), dtype=np.float32)


@pytest.fixture
def alert():
    return {
        "id": "A001", "family_id": "F01", "source": "edr", "rule": "Encoded command",
        "host": "ws-demo", "user": "demo", "source_ip": "192.0.2.4",
        "destination_ip": "198.51.100.9", "process": {
            "name": "powershell.exe", "command_line": "powershell -enc AAA", "parent": "cmd.exe"
        }, "timestamp": "2026-01-01T00:00:00Z", "event": {"ticket": "CHG-DEMO"},
    }


@pytest.fixture
def environment():
    return ToolEnvironment({
        "ip_reputation": {"198.51.100.9": {"source_id": "IP01", "facts": ["No prior sightings."]}},
        "user_context": {"demo": {"source_id": "USER01", "facts": ["Assigned to helpdesk."]}},
        "host_context": {"ws-demo": {"source_id": "HOST01", "facts": ["Workstation with active telemetry."]}},
    }, LocalRunbookIndex([Runbook("RB01", "Investigate", "Check process ancestry.", "one.md")], Encoder()))


def final():
    return json.dumps({
        "verdict": "needs_escalation", "severity": 3, "technique_id": None,
        "summary": "Activity requires additional context.",
        "evidence": [{"source_id": "USER01", "fact": "Assigned to helpdesk."}],
    })


def test_recording_executes_all_four_tools_and_exposes_only_observed_sources(alert, environment):
    recording = {"alert_id": "A001", "turns": [{"tool_calls": [
        {"name": "ip_reputation", "arguments": {"ip": "198.51.100.9"}},
        {"name": "user_context", "arguments": {"user": "demo"}},
        {"name": "host_context", "arguments": {"host": "ws-demo"}},
        {"name": "runbook_search", "arguments": {"query": "process ancestry", "top_k": 1}},
    ]}, {"content": final()}]}
    result = asyncio.run(run_recorded(alert, recording, environment))
    assert result.decision["verdict"] == "needs_escalation"
    assert result.tool_calls == 4 and result.generation_count == 2
    assert set(result.exposures) == {"alert:A001", "IP01", "USER01", "HOST01", "RB01"}
    assert [entry["tool"] for entry in result.trace] == [
        "ip_reputation", "user_context", "host_context", "runbook_search"
    ]
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 4
    assert '"score"' in tool_messages[-1].text
    assert "reference" not in result.messages[0].text.lower()


def test_missing_lookup_records_uncertainty_and_does_not_leak_unqueried_context(alert, environment):
    recording = {"alert_id": "A001", "turns": [
        {"tool_calls": [{"name": "host_context", "arguments": {"host": "missing-host"}}]},
        {"content": final()},
    ]}
    result = asyncio.run(run_recorded(alert, recording, environment))
    assert "HOST01" not in result.exposures
    assert result.trace[0]["result"]["found"] is False
    assert "USER01" not in result.exposures  # An unsupported citation is left for the scorer to reject.


def test_tool_limit_rejects_oversized_batch_before_executing_any_tools(alert, environment):
    calls = [{"name": "host_context", "arguments": {"host": "ws-demo"}}] * 7
    result = asyncio.run(run_agent(alert, RecordedAdapter({"turns": [{"tool_calls": calls}]}), environment))
    assert result.stop_reason == "tool_limit"
    assert result.tool_calls == 0 and result.trace == []
    assert result.decision is None


def test_unknown_tools_and_invalid_arguments_preserve_observed_errors(alert, environment):
    recording = {"alert_id": "A001", "turns": [{"tool_calls": [
        {"name": "unknown_tool", "arguments": {}},
        {"name": "host_context", "arguments": {"wrong_argument": "ws-demo"}},
    ]}, {"content": final()}]}
    result = asyncio.run(run_recorded(alert, recording, environment))
    assert result.tool_calls == len(result.trace) == 2
    assert all(entry["error"] for entry in result.trace)
    assert set(result.exposures) == {"alert:A001"}
    assert len([m for m in result.messages if m.role == "tool"]) == 2


def test_generation_limit_does_not_allow_a_fifth_tool_round(alert, environment):
    turn = {"tool_calls": [{"name": "host_context", "arguments": {"host": "ws-demo"}}]}
    result = asyncio.run(run_agent(alert, RecordedAdapter({"turns": [turn] * 6}), environment))
    assert result.stop_reason == "generation_limit"
    assert result.generation_count == 5 and result.tool_calls == 4


def test_answer_schema_rejects_coercion_and_extra_answer_fields():
    value = json.loads(final())
    value["severity"] = "3"
    assert parse_decision(json.dumps(value))[0] is None
    value["severity"] = 3
    value["confidence"] = 0.9
    assert parse_decision(json.dumps(value))[0] is None


def test_input_rejects_reference_labels(alert):
    alert["target"] = {"verdict": "benign"}
    with pytest.raises(ValueError):
        Alert.model_validate(alert)


def test_live_budget_denial_prevents_provider_dispatch(monkeypatch, environment):
    dispatched = []

    class Ledger:
        def reserve(self, *args):
            raise RuntimeError("budget exhausted")

    class Model:
        async def generate(self, **kwargs):
            dispatched.append(kwargs)

    monkeypatch.setattr("soc_triage.agent.get_model", lambda *args, **kwargs: Model())
    adapter = LiveInspectAdapter("openai/example-model", Ledger())
    with pytest.raises(RuntimeError, match="budget exhausted"):
        asyncio.run(adapter.generate([], environment.inspect_tools(), "auto"))
    assert dispatched == []


def test_live_ambiguous_failure_holds_full_reservation(monkeypatch, environment):
    events = []

    class Ledger:
        def reserve(self, *args):
            events.append("reserve")
            return SimpleNamespace(id="r1")

        def mark_uncertain(self, reservation_id):
            events.append(("uncertain", reservation_id))

    class Model:
        async def generate(self, **kwargs):
            events.append("dispatch")
            raise ConnectionError("response lost")

    monkeypatch.setattr("soc_triage.agent.get_model", lambda *args, **kwargs: Model())
    adapter = LiveInspectAdapter("anthropic/example-model", Ledger())
    with pytest.raises(ConnectionError):
        asyncio.run(adapter.generate([], environment.inspect_tools(), "auto"))
    assert events == ["reserve", "dispatch", ("uncertain", "r1")]


def test_live_settles_exact_usage_and_disables_both_retry_layers(monkeypatch, environment):
    settings = {}
    settlements = []

    class Ledger:
        def reserve(self, model, input_bound, output_bound, purpose):
            assert input_bound > 8192
            assert output_bound == 1024
            return SimpleNamespace(id="r2")

        def settle(self, *args, **kwargs):
            settlements.append((args, kwargs))

    class Model:
        async def generate(self, **kwargs):
            assert kwargs["cache"] is False
            output = ModelOutput.from_content("returned-snapshot", final())
            output.usage = ModelUsage(
                input_tokens=42, output_tokens=16, total_tokens=73,
                input_tokens_cache_read=10, input_tokens_cache_write=5,
            )
            return output

    def factory(*args, **kwargs):
        settings.update(kwargs)
        return Model()

    monkeypatch.setattr("soc_triage.agent.get_model", factory)
    adapter = LiveInspectAdapter("openai/example-model", Ledger())
    asyncio.run(adapter.generate([], environment.inspect_tools(), "auto"))
    assert settings["config"].max_retries == 0 and settings["max_retries"] == 0
    assert settings["responses_api"] is True and settings["streaming"] is False
    assert settlements == [(("r2", 42, 16), {"cache_read_tokens": 10, "cache_write_tokens": 5})]
