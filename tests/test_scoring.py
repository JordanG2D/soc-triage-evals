from copy import deepcopy

import pytest

from soc_triage.reporting import build_report, check_regression
from soc_triage.scoring import aggregate_scores, score_case


def sample():
    reference = {
        "alert_id": "TEST001", "family_id": "test_family", "event_truth": "malicious",
        "expected_verdict": "needs_escalation", "severity": 2,
        "acceptable_technique_ids": [None, "T0000"],
        "required_facts": [{"id": "test-fact", "fact": "Observed failed access.", "supporting_ids": ["user:fake"]}],
        "tool_policy": {"required_any_of": [["user_context", "host_context"], ["ip_reputation"]], "optional": ["runbook_search"], "forbidden": ["shell"]},
        "max_tool_calls": 3,
    }
    result = {
        "alert_id": "TEST001", "decision": {"verdict": "needs_escalation", "severity": 3, "technique_id": None, "summary": "Further review required.", "evidence": [{"source_id": "user:fake", "fact": "Observed failed access."}]},
        "parse_error": None, "trace": [{"tool": "host_context", "result": {}}, {"tool": "ip_reputation", "result": {}}],
        "exposures": {"user:fake": {"facts": ["Observed failed access."]}},
    }
    return reference, result


def test_action_truth_cost_and_alternative_tools_are_separate():
    reference, result = sample()
    score = score_case(reference, result)
    assert score["verdict_correct"] is True
    assert score["error_cost"] == 2  # correct escalation need not imply known-benign event
    assert score["severity_exact"] is False
    assert score["severity_within_one"] is True
    assert score["severity_absolute_error"] == 1
    assert score["technique_acceptable"] is True
    assert score["tool_requirement_coverage"] == 1
    assert score["extra_tool_calls"] == 0
    assert score["required_fact_exact_text_hits"] == 1


def test_valid_id_is_not_a_semantic_faithfulness_claim():
    reference, result = sample()
    result["decision"]["evidence"][0]["fact"] = "An invented claim."
    score = score_case(reference, result)
    assert score["citation_id_validity"] == 1
    assert score["required_fact_exact_text_hits"] == 0
    assert score["faithfulness"] == "uncalibrated_pending_human_labels"
    result["decision"]["evidence"][0]["source_id"] = "reference-only-source"
    reference["required_facts"][0]["supporting_ids"].append("reference-only-source")
    assert score_case(reference, result)["invalid_citation_count"] == 1


def test_false_benign_is_largest_cost_and_extras_are_visible():
    reference, result = sample()
    result["decision"]["verdict"] = "benign"
    result["trace"] += [{"tool": "shell"}, {"tool": "shell"}, {"tool": "new_tool"}]
    score = score_case(reference, result)
    assert score["error_cost"] == 10
    assert score["false_benign_on_malicious"]
    assert score["forbidden_tool_calls"] == 2
    assert score["extra_tool_calls"] == 3
    assert score["repeated_tool_calls"] == 1
    assert score["tool_budget_exceeded"]


def test_missing_null_is_not_explicit_null_and_invalid_outputs_remain_in_denominators():
    reference, result = sample()
    del result["decision"]["technique_id"]
    assert score_case(reference, result)["technique_acceptable"] is False
    result["parse_error"] = "bad JSON"
    invalid = score_case(reference, result)
    assert invalid["error_cost"] == 10
    assert invalid["predicted_verdict"] == "invalid"
    assert invalid["severity_absolute_error"] is None
    aggregate = aggregate_scores([invalid])
    assert aggregate["case_count"] == 1
    assert aggregate["verdict_accuracy"] == 0
    assert aggregate["severity_exact_accuracy"] == 0
    assert aggregate["severity_mae_valid_count"] == 0
    assert aggregate["severity_mae"] is None
    assert aggregate["verdict_confusion"]["needs_escalation"]["invalid"] == 1


def test_pairing_and_aggregation_refuse_identity_errors():
    reference, result = sample()
    result["alert_id"] = "OTHER"
    with pytest.raises(ValueError, match="IDs"):
        score_case(reference, result)
    result["alert_id"] = "TEST001"
    score = score_case(reference, result)
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_scores([score, deepcopy(score)])


def test_failed_tool_attempts_are_counted_but_do_not_cover_required_investigation():
    reference, result = sample()
    result["trace"][0]["error"] = {"type": "parsing", "message": "invalid arguments"}
    result["tool_calls"] = 2
    score = score_case(reference, result)
    assert score["tool_calls"] == 2
    assert score["failed_tool_calls"] == 1
    assert score["tool_requirement_coverage"] == 0.5
    result["tool_calls"] = 3
    with pytest.raises(ValueError, match="failed attempts"):
        score_case(reference, result)


def test_fixture_report_cost_and_regression_do_not_make_model_claims():
    reference, result = sample()
    report = build_report([score_case(reference, result)], execution_mode="offline_fixture", metadata={"cost_usd": 99})
    assert report["metadata"]["cost_usd"] == 0
    assert report["faithfulness_judge"]["agreement_rate"] is None
    with pytest.raises(ValueError, match="latency"):
        build_report([score_case(reference, result)], execution_mode="offline_fixture", metadata={"model_latency_seconds": 0.1})
    assert check_regression(report["metrics"], {"case_count": 1})["status"] == "pass"
    assert check_regression(report["metrics"], {"not_present": 0})["status"] == "fail"
