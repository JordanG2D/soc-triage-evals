"""Structure/arithmetic tests on invented TEST records, never human labeling."""

import asyncio
from copy import deepcopy
import json

import pytest

from soc_triage.judge import export_human_pack, generate_judgments, judge_agreement, validate_human_labels
from soc_triage.cli import main


def synthetic_test_records(count=20):
    __tracebackhide__ = True
    return [{
        "alert": {"id": f"TEST{i:03}", "event": {"test_value": i}},
        "result": {"alert_id": f"TEST{i:03}", "model": "TEST_MODEL_IDENTITY", "raw_output": '{"test":true}', "trace": [{"tool": "test_tool", "arguments": {}, "result": {"test_observation": i}}], "exposures": {}},
        "provenance": {"execution_mode": "live_model", "run_id": "UNIT_TEST_NOT_AN_ACTUAL_RESPONSE", "source_commit": "UNIT_TEST_SOURCE"},
        "reference": {"expected_verdict": "DO_NOT_EXPORT"},
    } for i in range(count)]


def test_pack_is_exactly_20_blank_and_blinded_and_ignores_fixtures():
    records = synthetic_test_records()
    fixture = deepcopy(records[0])
    fixture["provenance"]["execution_mode"] = "offline_fixture"
    pack = export_human_pack(records + [fixture])
    assert len(pack["responses"]) == 20
    assert all(response["human_label"] == {"faithful": None, "reason": "", "unsupported_claims": []} for response in pack["responses"])
    assert all(set(response) == {"response_id", "source_sha256", "displayed_material_sha256", "alert", "observed_tools", "final_response", "human_label"} for response in pack["responses"])
    assert "TEST_MODEL_IDENTITY" not in str(pack)
    assert "DO_NOT_EXPORT" not in str(pack)
    with pytest.raises(ValueError, match="20 actual"):
        export_human_pack(records[:19])
    with pytest.raises(ValueError, match="duplicate"):
        export_human_pack(records + [records[0]])


def test_incomplete_human_review_refuses_generation_and_agreement():
    pack = export_human_pack(synthetic_test_records())
    async def forbidden_callback(prompt):
        pytest.fail("must not generate before complete human labels")
    with pytest.raises(ValueError, match="human_reviewer"):
        asyncio.run(generate_judgments(pack, forbidden_callback))
    pack["human_reviewer"] = "TEST_REVIEWER"
    pack["human_labeled_at"] = "TEST_TIME"
    with pytest.raises(ValueError, match="missing human"):
        judge_agreement(pack, [])


def test_cli_reports_pending_before_reading_nonexistent_judge_labels(tmp_path):
    pack_path = tmp_path / "blank-test-pack.json"
    export_human_pack(synthetic_test_records(), pack_path)
    output = tmp_path / "agreement.json"
    assert main(["judge-agreement", "--human-pack", str(pack_path), "--judgments", str(tmp_path / "does-not-exist.json"), "--output", str(output)]) == 2
    pending = json.loads(output.read_text())
    assert pending["status"] == "pending_human_labels"
    assert pending["agreement_rate"] is None
    assert all(response["human_label"]["faithful"] is None for response in json.loads(pack_path.read_text())["responses"])


def test_agreement_arithmetic_and_integrity_use_explicit_test_values():
    pack = export_human_pack(synthetic_test_records())
    pack["human_reviewer"] = "TEST_REVIEWER_NOT_HUMAN_EVIDENCE"
    pack["human_labeled_at"] = "TEST_TIME"
    predictions = []
    # This truth table tests arithmetic only, not model/human agreement.
    for index, response in enumerate(pack["responses"]):
        human = index < 10
        response["human_label"] = {"faithful": human, "reason": "TEST truth-table value only", "unsupported_claims": []}
        predictions.append({"response_id": response["response_id"], "source_sha256": response["source_sha256"], "faithful": index % 2 == 0})
    agreement = judge_agreement(pack, predictions)
    assert agreement["agreement_rate"] == 0.5
    assert agreement["confusion_2x2"] == {"human_faithful": {"judge_faithful": 5, "judge_unfaithful": 5}, "human_unfaithful": {"judge_faithful": 5, "judge_unfaithful": 5}}
    with pytest.raises(ValueError, match="all 20"):
        judge_agreement(pack, predictions[:-1])
    pack["responses"][0]["final_response"] = "altered"
    with pytest.raises(ValueError, match="evidence changed"):
        validate_human_labels(pack)


def test_predeclared_sample_requires_all_cases_for_every_configuration():
    records = synthetic_test_records(10)
    for index in range(10):
        second = deepcopy(records[index])
        second["result"]["model"] = "SECOND_TEST_MODEL"
        records.append(second)
    ids = [f"TEST{i:03}" for i in range(10)]
    pack = export_human_pack(records, predeclared_alert_ids=ids)
    assert pack["selection"]["predeclared_alert_ids"] == ids
    assert len(pack["responses"]) == 20
    with pytest.raises(ValueError, match="20 actual"):
        export_human_pack(records[:-1], predeclared_alert_ids=ids)
