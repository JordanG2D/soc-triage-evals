"""OFFLINE UNIT TESTS ONLY: fake native batches, no provider requests.

The wrapper's production envelopes say live_model because that is the boundary
under test. Every generated file stays in pytest temporary storage, marked
OFFLINE_TEST_ONLY, and every fake response identifies itself as a placeholder.
These artifacts are neither actual live evidence nor human calibration data.
"""

import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from soc_triage import live
from soc_triage.budget import MODELS
from soc_triage.judge import canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
FAKE_NOTICE = "OFFLINE UNIT TEST PLACEHOLDER: no provider was called; not a triage or faithfulness judgment."
FAKE_USAGES = [
    {"input_tokens": 100, "output_tokens": 10, "input_tokens_cache_read": 20, "input_tokens_cache_write": 5},
    {"input_tokens": 30, "output_tokens": 4, "input_tokens_cache_read": None, "input_tokens_cache_write": None},
]


class FakeBatch:
    """A native batch substitute that accounts for explicit artificial usage."""

    def __init__(self, alerts):
        self.alerts = alerts
        self.calls = []

    def __call__(self, model, ledger, **paths):
        self.calls.append({"model": model, "lease_id": ledger.lease_id, **paths})
        batch = []
        for alert_id, alert in sorted(self.alerts.items()):
            decision = {"verdict": "needs_escalation", "severity": 3, "technique_id": None,
                        "summary": FAKE_NOTICE, "evidence": [], "next_action": FAKE_NOTICE}
            for usage in FAKE_USAGES:
                reservation = ledger.reserve(model, 150, 20, "OFFLINE UNIT TEST artificial request")
                ledger.settle(reservation.id, usage["input_tokens"], usage["output_tokens"],
                              cache_read_tokens=usage["input_tokens_cache_read"] or 0,
                              cache_write_tokens=usage["input_tokens_cache_write"] or 0)
            batch.append({
                "alert_id": alert_id, "family_id": alert["family_id"], "model": model,
                "prompt_version": "v1", "decision": decision, "parse_error": None,
                "raw_output": json.dumps(decision), "trace": [], "tool_calls": 0,
                "exposures": {f"alert:{alert_id}": deepcopy(alert)},
                "generations": [{"usage": deepcopy(usage), "offline_unit_test": True} for usage in FAKE_USAGES],
                "latency_seconds": int(alert_id[1:]) / 10 + MODELS.index(model),
            })
        return batch


@pytest.fixture
def offline_wrapper(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    for key, value in {
        "OPENAI_API_KEY": "offline-fake-openai-key",
        "ANTHROPIC_API_KEY": "offline-fake-anthropic-key",
        "GH_TOKEN": "offline-fake-github-token",
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": live.REPOSITORY,
        "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": "801",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)
    output = tmp_path / "OFFLINE_TEST_ONLY_wrapper_outputs"
    output.mkdir()
    (output / "OFFLINE_TEST_ONLY.txt").write_text(FAKE_NOTICE)
    lease = {"run_id": "801:1", "microdollars": 5_000_000, "source_commit": "a" * 40,
             "allocated_at": "2026-11-12T12:00:00+00:00", "journal_commit": "b" * 40}
    lease_path = tmp_path / "OFFLINE_TEST_ONLY_lease.json"
    lease_path.write_text(json.dumps(lease))
    # An orphaned earlier allocation remains consumed without blocking this
    # independent, already allocated run's normal path.
    journal = {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [
        {"run_id": "800:1", "microdollars": 5_000_000},
        {key: value for key, value in lease.items() if key != "journal_commit"},
    ]}
    remote_requests = []
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("?ref=" + "b" * 40)
        assert timeout == 30
        remote_requests.append(request.full_url)
        body = {"content": base64.b64encode(json.dumps(journal).encode()).decode()}
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(live.urllib.request, "urlopen", fake_urlopen)
    alerts = live._load_directory(ROOT / "data/alerts", "id")
    native = FakeBatch(alerts)
    monkeypatch.setattr(live, "run_live_task_sync", native)
    args = SimpleNamespace(lease=lease_path, ledger=tmp_path / "OFFLINE_TEST_ONLY_budget.sqlite",
                           output=output, data_dir=ROOT / "data", runbooks_dir=ROOT / "runbooks",
                           model_dir=tmp_path / "OFFLINE_TEST_ONLY_unused_embedding_model")
    return SimpleNamespace(args=args, native=native, journal=journal, lease=lease,
                           remote_requests=remote_requests)


def test_offline_fake_batches_produce_32_scores_reports_and_20_blank_human_views(offline_wrapper, monkeypatch):
    setup = offline_wrapper
    scored = []
    real_score = live.score_case
    def observed_score(reference, result):
        scored.append((result["model"], result["alert_id"]))
        return real_score(reference, result)
    monkeypatch.setattr(live, "score_case", observed_score)
    assert live.run_live_slice(setup.args) == 0
    assert [call["model"] for call in setup.native.calls] == list(MODELS)
    assert len(setup.remote_requests) == 1
    records = [json.loads(line) for line in (setup.args.output / "records.jsonl").read_text().splitlines()]
    expected_pairs = {(model, alert_id) for model in MODELS for alert_id in setup.native.alerts}
    assert len(records) == len(scored) == 32
    assert set(scored) == expected_pairs
    assert {(record["result"]["model"], record["alert"]["id"]) for record in records} == expected_pairs
    for record in records:
        result, provenance = record["result"], record["provenance"]
        model, alert_id = result["model"], result["alert_id"]
        assert FAKE_NOTICE in result["raw_output"]
        assert provenance["execution_mode"] == "live_model"  # Wrapper contract, fake unit output only.
        assert provenance["model"] == model
        assert provenance["run_id"] == "801:1"
        assert provenance["source_commit"] == "a" * 40
        assert provenance["journal_commit"] == "b" * 40
        assert provenance["prompt_version"] == "v1"
        assert datetime.fromisoformat(provenance["timestamp"]).tzinfo is not None
        assert provenance["cost_upper_microdollars"] == 760
        expected_cost = 0.000020825 if model == MODELS[0] else 0.000212
        assert provenance["estimated_standard_cost_usd"] == pytest.approx(expected_cost)
        assert provenance["end_to_end_response_latency_seconds"] == int(alert_id[1:]) / 10 + MODELS.index(model)
        assert "latency_seconds" not in result
        alert_path = setup.args.data_dir / "alerts" / f"{alert_id}.json"
        assert provenance["input_sha256"][str(alert_path)] == hashlib.sha256(alert_path.read_bytes()).hexdigest()
        embedding_config = Path("config/embedding.json")
        assert provenance["input_sha256"][str(embedding_config)] == hashlib.sha256(embedding_config.read_bytes()).hexdigest()
    reports = [json.loads((setup.args.output / model.split("/")[0] / "report.json").read_text()) for model in MODELS]
    assert sum(report["metrics"]["case_count"] for report in reports) == 32
    for model, report in zip(MODELS, reports):
        assert len(report["cases"]) == 16
        assert {case["alert_id"] for case in report["cases"]} == set(setup.native.alerts)
        assert report["metadata"]["model"] == model
        assert report["metadata"]["source_commit"] == "a" * 40
        assert len(report["metadata"]["end_to_end_response_latency_seconds"]) == 16
        assert report["faithfulness_judge"]["agreement_rate"] is None
        assert report["faithfulness_judge"]["status"] == "UNCALIBRATED_PENDING_20_HUMAN_LABELS"
        assert report["paired_comparison"]["metrics"]["error_cost"]["case_count"] == 16
        assert report["paired_comparison"]["metrics"]["error_cost"]["family_count"] == 8
    pack = json.loads((setup.args.output / "human-calibration.json").read_text())
    assert len(pack["responses"]) == 20
    assert pack["selection"]["predeclared_alert_ids"] == list(live.CALIBRATION_ALERT_IDS)
    assert "human_reviewer" not in pack and "human_labeled_at" not in pack
    source_by_hash = {canonical_sha256(record): record for record in records}
    selected = []
    for response in pack["responses"]:
        assert response["human_label"] == {"faithful": None, "reason": "", "unsupported_claims": []}
        assert FAKE_NOTICE in response["final_response"]
        assert "expected_verdict" not in response
        source = source_by_hash[response["source_sha256"]]
        selected.append((source["result"]["model"], source["alert"]["id"]))
    assert Counter(model for model, _ in selected) == {model: 10 for model in MODELS}
    assert set(selected) == {(model, alert_id) for model in MODELS for alert_id in live.CALIBRATION_ALERT_IDS}
    budget = json.loads((setup.args.output / "budget.json").read_text())
    assert budget["lease_id"] == "801:1"
    assert budget["cap_microdollars"] == 5_000_000
    assert budget["charged_upper_microdollars"] == 32 * 760
    assert budget["states"]["settled"]["count"] == 64


@pytest.mark.parametrize("secret", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
def test_missing_secret_rejected_before_remote_or_native_call(offline_wrapper, monkeypatch, secret):
    setup = offline_wrapper
    monkeypatch.delenv(secret)
    with pytest.raises(ValueError, match="Missing required secret"):
        live.run_live_slice(setup.args)
    assert setup.native.calls == []
    assert setup.remote_requests == []
    assert not setup.args.ledger.exists()


@pytest.mark.parametrize("field,value", [("run_id", "802:1"), ("source_commit", "c" * 40), ("microdollars", 5_000_000.0)])
def test_changed_lease_rejected_before_native_call(offline_wrapper, field, value):
    setup = offline_wrapper
    lease = {**setup.lease, field: value}
    setup.args.lease.write_text(json.dumps(lease))
    with pytest.raises(ValueError):
        live.run_live_slice(setup.args)
    assert setup.native.calls == []
    assert setup.remote_requests == []
    assert not setup.args.ledger.exists()


@pytest.mark.parametrize("change", ["schema", "duplicate", "cap", "missing-current"])
def test_malformed_or_unmatched_remote_history_rejected_before_native_call(offline_wrapper, change):
    setup = offline_wrapper
    if change == "schema":
        setup.journal["schema_version"] = True
    elif change == "duplicate":
        setup.journal["allocations"].append(deepcopy(setup.journal["allocations"][-1]))
    elif change == "cap":
        setup.journal["cap_microdollars"] = 20_000_000.0
    else:
        setup.journal["allocations"].pop()
    with pytest.raises(ValueError):
        live.run_live_slice(setup.args)
    assert setup.native.calls == []
    assert len(setup.remote_requests) == 1
    assert not setup.args.ledger.exists()


@pytest.mark.parametrize("failing_model", MODELS)
def test_budget_json_survives_artificial_provider_error(offline_wrapper, monkeypatch, failing_model):
    setup = offline_wrapper
    def failing_batch(model, ledger, **paths):
        if model == failing_model:
            reservation = ledger.reserve(model, 100, 20, "OFFLINE UNIT TEST ambiguous provider failure")
            ledger.mark_uncertain(reservation.id)
            raise RuntimeError("OFFLINE UNIT TEST artificial provider error; no provider called")
        return setup.native(model, ledger, **paths)
    monkeypatch.setattr(live, "run_live_task_sync", failing_batch)
    with pytest.raises(RuntimeError, match="OFFLINE UNIT TEST artificial provider error"):
        live.run_live_slice(setup.args)
    completed = 0 if failing_model == MODELS[0] else 16
    budget = json.loads((setup.args.output / "budget.json").read_text())
    assert budget["charged_upper_microdollars"] == completed * 760 + 600
    assert budget["states"]["uncertain"] == {"count": 1, "charge_microdollars": 600}
    records_path = setup.args.output / "records.jsonl"
    assert (len(records_path.read_text().splitlines()) if records_path.exists() else 0) == completed
    assert not (setup.args.output / "human-calibration.json").exists()


def test_incomplete_native_batch_rejected_and_budget_preserved(offline_wrapper, monkeypatch):
    setup = offline_wrapper
    def incomplete_batch(model, ledger, **paths):
        return setup.native(model, ledger, **paths)[:-1]
    monkeypatch.setattr(live, "run_live_task_sync", incomplete_batch)
    with pytest.raises(ValueError, match="all 16 development responses"):
        live.run_live_slice(setup.args)
    assert len(setup.native.calls) == 1
    budget = json.loads((setup.args.output / "budget.json").read_text())
    assert budget["charged_upper_microdollars"] == 16 * 760
    assert not (setup.args.output / "records.jsonl").exists()
    assert not (setup.args.output / "human-calibration.json").exists()
