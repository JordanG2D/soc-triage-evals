"""Real provider converters and SDK serialization over offline HTTP transports."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model

from soc_triage.agent import LiveInspectAdapter
from soc_triage.prompts import SYSTEM_PROMPT, alert_prompt
from soc_triage.schema import Alert
from soc_triage.structured_output import canonical_json, common_decision_schema, output_contract_metadata
from soc_triage.tools import ToolEnvironment


MODELS = {
    "openai": "openai/gpt-6-luna",
    "anthropic": "anthropic/claude-haiku-4-5-20251001",
}


class RecordingLedger:
    def __init__(self):
        self.reservations = []
        self.settlements = []

    def reserve(self, *arguments):
        self.reservations.append(arguments)
        return SimpleNamespace(id=f"offline-{len(self.reservations)}")

    def settle(self, *arguments, **keywords):
        self.settlements.append((arguments, keywords))

    def mark_uncertain(self, identifier):
        pytest.fail(f"Unexpected uncertain offline reservation: {identifier}")


def _response(provider, probe=False):
    if provider == "openai":
        return {
            "id": "resp_offline_mock", "object": "response", "created_at": 0,
            "status": "completed", "model": "gpt-6-luna",
            "output": [{
                "id": "msg_offline_mock", "type": "message", "status": "completed",
                "role": "assistant", "content": [{"type": "output_text", "text": "{}", "annotations": []}],
            }],
            "usage": {"input_tokens": 7 if probe else 11, "output_tokens": 3 if probe else 17, "total_tokens": 10 if probe else 28},
        }
    return {
        "id": "msg_offline_mock", "type": "message", "role": "assistant",
        "model": "claude-haiku-4-5-20251001", "content": [{"type": "text", "text": "{}"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 17},
    }


def _system_text(provider, body):
    if provider == "anthropic":
        system = body["system"]
        return system if isinstance(system, str) else "".join(block["text"] for block in system)
    return "".join(
        item["content"] if isinstance(item["content"], str)
        else "".join(block["text"] for block in item["content"])
        for item in body["input"] if item.get("role") in {"system", "developer"}
    )


def _wire_schema(provider, body):
    return body["text"]["format"]["schema"] if provider == "openai" else body["output_config"]["format"]["schema"]


def _run_capture(monkeypatch, provider, choices, historical=False):
    """Exercise the complete LiveInspectAdapter with no network-capable transport."""
    captured = []
    ledger = RecordingLedger()

    async def handler(request):
        assert request.url.path == ("/v1/responses" if provider == "openai" else "/v1/messages")
        body = json.loads(request.content)
        captured.append({
            "path": request.url.path, "body": body,
            # Never retain authentication, cookies, or arbitrary SDK headers.
            "headers": {"anthropic-beta": request.headers["anthropic-beta"]} if "anthropic-beta" in request.headers else {},
        })
        probe = body.get("input") == "Please say 'hello, world'"
        return httpx2.Response(200, json=_response(provider, probe))

    def model_factory(*arguments, **keywords):
        if historical:
            keywords.pop("extra_body", None)
        keywords["http_client"] = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        model = get_model(*arguments, **keywords)
        # Header-only OS discovery is unrelated to the request contract. Keep
        # it deterministic and avoid an executor dependency in offline tests.
        model.api.client._platform = "Linux"
        return model

    monkeypatch.setattr("soc_triage.agent.get_model", model_factory)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-dummy-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-dummy-key")
    packet = Alert.model_validate_json(Path("data/alerts/A001.json").read_text())
    messages = [ChatMessageSystem(content=SYSTEM_PROMPT), ChatMessageUser(content=alert_prompt(packet))]
    environment = ToolEnvironment({}, None)  # Definitions only; no tool is executed.

    async def run():
        adapter = LiveInspectAdapter(MODELS[provider], ledger)
        if historical:
            adapter.config.response_schema = None
            adapter.config.reasoning_summary = None
        try:
            outputs = []
            for choice in choices:
                if historical:
                    # Reproduce the former reservation/generate/settle pattern
                    # with its exact provider configuration. The current
                    # adapter deliberately requires its native output schema.
                    reservation = ledger.reserve(MODELS[provider], 20_000, 1024, "offline_historical_reproduction")
                    output = await adapter._model.generate(
                        input=messages, tools=environment.inspect_tools(), tool_choice=choice,
                        config=adapter.config, cache=False,
                    )
                    ledger.settle(reservation.id, output.usage.input_tokens, output.usage.output_tokens,
                                  cache_read_tokens=output.usage.input_tokens_cache_read or 0,
                                  cache_write_tokens=output.usage.input_tokens_cache_write or 0)
                else:
                    output = await adapter.generate(messages, environment.inspect_tools(), choice)
                outputs.append(output)
            contract = deepcopy(adapter.last_request_contract)
        finally:
            await adapter.close()
        return outputs, contract

    return (*asyncio.run(run()), captured, ledger)


@pytest.mark.parametrize("provider", MODELS)
@pytest.mark.parametrize("choice", ["auto", "none"])
def test_every_generation_transmits_shared_native_grammar_and_exact_system(monkeypatch, provider, choice):
    outputs, contract, captured, ledger = _run_capture(monkeypatch, provider, [choice])
    assert len(captured) == len(ledger.reservations) == len(ledger.settlements) == 1
    request = captured[0]
    body = request["body"]
    assert _system_text(provider, body) == SYSTEM_PROMPT
    schema = _wire_schema(provider, body)
    assert schema == common_decision_schema()
    assert hashlib.sha256(canonical_json(schema).encode()).hexdigest() == contract["schema_sha256"]
    assert contract["protocol"] == "native-json-schema-v1"
    assert schema["properties"]["evidence"]["items"]["additionalProperties"] is False
    assert set(schema["properties"]["evidence"]["items"]["required"]) == {"source_id", "fact"}
    assert "$ref" not in canonical_json(schema) and "$defs" not in canonical_json(schema)
    assert ledger.reservations[0][1] > len(canonical_json(schema).encode()) + 8192
    assert outputs[0].usage.input_tokens == 11 and outputs[0].usage.output_tokens == 17
    if provider == "openai":
        assert body["text"]["format"]["strict"] is True
        assert body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 1024 and body["service_tier"] == "default"
    else:
        assert "anthropic-beta" not in request["headers"]
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert "output_format" not in body
        assert body["max_tokens"] == 1024
    if choice == "none":
        # Inspect's provider adapters differ in whether disabled declarations
        # remain present. Both requests prohibit additional tool actions.
        assert not body.get("tools") or body.get("tool_choice") in ("none", {"type": "none"})


@pytest.mark.parametrize("provider", MODELS)
def test_fresh_adapter_auto_then_final_has_one_http_request_per_reservation(monkeypatch, provider):
    _, _, captured, ledger = _run_capture(monkeypatch, provider, ["auto", "none"])
    assert len(captured) == len(ledger.reservations) == len(ledger.settlements) == 2
    assert all(_wire_schema(provider, request["body"]) == common_decision_schema() for request in captured)


def test_historical_openai_config_reproduces_extra_probe_and_omitted_probe_usage(monkeypatch):
    # A reproduction of the prior configuration, not a capture of a live run.
    outputs, _, captured, ledger = _run_capture(monkeypatch, "openai", ["auto", "none"], historical=True)
    assert len(captured) == 3 and len(ledger.reservations) == 2
    probe = captured[0]["body"]
    assert probe["input"] == "Please say 'hello, world'"
    assert probe["reasoning"] == {"effort": "low", "summary": "auto"}
    assert "max_output_tokens" not in probe
    assert "store" not in probe and "service_tier" not in probe
    assert all("text" not in request["body"] for request in captured)
    # Probe reports 7 input / 3 output tokens; each generation exposes only
    # its own 11 / 17 tokens to settlement, rather than their combined usage.
    assert [(output.usage.input_tokens, output.usage.output_tokens) for output in outputs] == [(11, 17), (11, 17)]
    assert [settlement[0][1:] for settlement in ledger.settlements] == [(11, 17), (11, 17)]


def test_historical_anthropic_config_is_prompt_only_without_implicit_schema(monkeypatch):
    _, _, captured, ledger = _run_capture(monkeypatch, "anthropic", ["auto", "none"], historical=True)
    assert len(captured) == len(ledger.reservations) == 2
    for request in captured:
        assert _system_text("anthropic", request["body"]) == SYSTEM_PROMPT
        assert not {"output_format", "output_config", "response_format"} & request["body"].keys()
        assert not request["headers"]
