"""Deterministic development scorers; citation validity is not faithfulness."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

VERDICTS = ("true_positive", "benign", "needs_escalation")
EVENT_TRUTHS = ("malicious", "benign", "unknown")
# Predeclared illustrative triage costs, not an operational loss estimate.
# Event truth and the expected triage action are deliberately separate axes.
ERROR_COSTS = {
    "malicious": {"true_positive": 0, "benign": 10, "needs_escalation": 2},
    "benign": {"true_positive": 3, "benign": 0, "needs_escalation": 1},
    "unknown": {"true_positive": 2, "benign": 4, "needs_escalation": 0},
}
INVALID_ACTION_COST = 10


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("result must be a mapping or provide to_dict()")
    return dict(value)


def _tool_name(call: Mapping[str, Any]) -> str:
    return str(call.get("tool", call.get("name", "<unnamed>")))


def score_case(reference: Mapping[str, Any], result: Any) -> dict[str, Any]:
    """Score one result using held-out-from-agent reference and exposure ledger.

    Missing or malformed predictions remain in accuracy/cost denominators. MAE
    is reported only for valid severity values, with its denominator explicit.
    Required fact text/source checks are mechanical, not semantic judgments.
    """
    result = _mapping(result)
    alert_id = str(reference["alert_id"])
    if str(result.get("alert_id")) != alert_id:
        raise ValueError("reference/result alert IDs do not match")
    truth = reference["event_truth"]
    expected = reference["expected_verdict"]
    if truth not in EVENT_TRUTHS or expected not in VERDICTS:
        raise ValueError("invalid reference event truth or expected verdict")
    severity = reference["severity"]
    if isinstance(severity, bool) or not isinstance(severity, int) or severity not in range(1, 5):
        raise ValueError("reference severity must be an integer from 1 to 4")
    decision = result.get("decision")
    valid_object = isinstance(decision, Mapping) and not result.get("parse_error")
    decision = dict(decision) if valid_object else {}
    predicted = decision.get("verdict")
    valid_verdict = predicted in VERDICTS
    predicted = predicted if valid_verdict else "invalid"
    predicted_severity = decision.get("severity")
    valid_severity = (
        not isinstance(predicted_severity, bool)
        and isinstance(predicted_severity, int)
        and predicted_severity in range(1, 5)
    )
    severity_error = abs(predicted_severity - severity) if valid_severity else None
    technique = decision.get("technique_id")
    acceptable = reference.get("acceptable_technique_ids", [])
    # A missing field must never accidentally earn the explicit-null credit.
    technique_ok = valid_object and "technique_id" in decision and technique in acceptable

    trace = result.get("trace", [])
    if not isinstance(trace, list) or any(not isinstance(call, Mapping) for call in trace):
        raise ValueError("trace must be a list of observed tool calls")
    declared_calls = result.get("tool_calls", len(trace))
    if type(declared_calls) is not int or declared_calls != len(trace):
        raise ValueError("actual tool call count and observed trace disagree; do not drop failed attempts")
    names = [_tool_name(call) for call in trace]
    counts = Counter(names)
    successful_names = {_tool_name(call) for call in trace if not call.get("error")}
    policy = reference.get("tool_policy", {})
    requirements = policy.get("required_any_of", [])
    if any(not isinstance(group, list) or not group for group in requirements):
        raise ValueError("each required_any_of group must contain tool alternatives")
    covered = [any(name in successful_names for name in group) for group in requirements]
    allowed = set(policy.get("optional", [])) | {name for group in requirements for name in group}
    forbidden = set(policy.get("forbidden", []))
    extra_calls = sum(count for name, count in counts.items() if name not in allowed)
    forbidden_calls = sum(counts[name] for name in forbidden)
    max_calls = reference.get("max_tool_calls", 6)

    exposures = result.get("exposures", {})
    if not isinstance(exposures, Mapping):
        raise ValueError("exposures must be the runner's observed source ledger")
    evidence = decision.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    cited_ids = [item.get("source_id") if isinstance(item, Mapping) else None for item in evidence]
    valid_citations = [isinstance(source_id, str) and source_id in exposures for source_id in cited_ids]
    cited_valid_ids = {source_id for source_id, valid in zip(cited_ids, valid_citations) if valid}
    required_facts = reference.get("required_facts", [])
    response_facts = {
        " ".join(str(item.get("fact", "")).casefold().split())
        for item in evidence if isinstance(item, Mapping)
    }
    fact_text_hits = [" ".join(str(fact["fact"]).casefold().split()) in response_facts for fact in required_facts]
    fact_source_hits = [bool(set(fact.get("supporting_ids", [])) & cited_valid_ids) for fact in required_facts]
    cost = ERROR_COSTS[truth][predicted] if valid_verdict else INVALID_ACTION_COST
    return {
        "alert_id": alert_id,
        "family_id": reference.get("family_id", result.get("family_id")),
        "event_truth": truth,
        "expected_verdict": expected,
        "predicted_verdict": predicted,
        "output_valid": bool(valid_object and valid_verdict and valid_severity),
        "parse_error": result.get("parse_error"),
        "verdict_correct": predicted == expected,
        "error_cost": cost,
        "always_escalate_cost": ERROR_COSTS[truth]["needs_escalation"],
        "false_benign_on_malicious": truth == "malicious" and predicted == "benign",
        "severity_valid": valid_severity,
        "severity_exact": severity_error == 0,
        "severity_within_one": severity_error is not None and severity_error <= 1,
        "severity_absolute_error": severity_error,
        "technique_acceptable": bool(technique_ok),
        "tool_calls": len(names),
        "failed_tool_calls": sum(bool(call.get("error")) for call in trace),
        "tool_requirements_met": sum(covered),
        "tool_requirement_count": len(covered),
        "tool_requirement_coverage": sum(covered) / len(covered) if covered else 1.0,
        "tool_policy_all_requirements_met": all(covered),
        "extra_tool_calls": extra_calls,
        "extra_tool_names": sorted(set(names) - allowed),
        "forbidden_tool_calls": forbidden_calls,
        "repeated_tool_calls": sum(count - 1 for count in counts.values()),
        "tool_budget_exceeded": len(names) > max_calls,
        "citation_count": len(cited_ids),
        "valid_citation_count": sum(valid_citations),
        "invalid_citation_count": len(cited_ids) - sum(valid_citations),
        "citation_id_validity": sum(valid_citations) / len(cited_ids) if cited_ids else None,
        "required_fact_count": len(required_facts),
        "required_fact_exact_text_hits": sum(fact_text_hits),
        "required_fact_support_id_hits": sum(fact_source_hits),
        "faithfulness": "uncalibrated_pending_human_labels",
    }


def aggregate_scores(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate all supplied cases, refusing duplicate IDs or empty input."""
    if not scores:
        raise ValueError("cannot aggregate an empty evaluation")
    ids = [score["alert_id"] for score in scores]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scored alert IDs")
    count = len(scores)
    confusion = {expected: {predicted: 0 for predicted in (*VERDICTS, "invalid")} for expected in VERDICTS}
    for score in scores:
        confusion[score["expected_verdict"]][score["predicted_verdict"]] += 1
    mean = lambda key: sum(float(score[key]) for score in scores) / count
    severity_errors = [score["severity_absolute_error"] for score in scores if score["severity_absolute_error"] is not None]
    citations = sum(score["citation_count"] for score in scores)
    valid_citations = sum(score["valid_citation_count"] for score in scores)
    facts = sum(score["required_fact_count"] for score in scores)
    return {
        "case_count": count,
        "verdict_accuracy": mean("verdict_correct"),
        "verdict_confusion": confusion,
        "mean_error_cost": mean("error_cost"),
        "always_escalate_mean_error_cost": mean("always_escalate_cost"),
        "always_escalate_verdict_accuracy": sum(score["expected_verdict"] == "needs_escalation" for score in scores) / count,
        "false_benign_on_malicious_count": sum(score["false_benign_on_malicious"] for score in scores),
        "malicious_case_count": sum(score["event_truth"] == "malicious" for score in scores),
        "invalid_output_count": sum(not score["output_valid"] for score in scores),
        "severity_exact_accuracy": mean("severity_exact"),
        "severity_within_one_accuracy": mean("severity_within_one"),
        "severity_mae": sum(severity_errors) / len(severity_errors) if severity_errors else None,
        "severity_mae_valid_count": len(severity_errors),
        "technique_accuracy": mean("technique_acceptable"),
        "mean_tool_requirement_coverage": mean("tool_requirement_coverage"),
        "tool_policy_all_requirements_met_rate": mean("tool_policy_all_requirements_met"),
        "total_tool_calls": sum(score["tool_calls"] for score in scores),
        "failed_tool_calls": sum(score["failed_tool_calls"] for score in scores),
        "tool_requirements_met": sum(score["tool_requirements_met"] for score in scores),
        "tool_requirement_count": sum(score["tool_requirement_count"] for score in scores),
        "extra_tool_calls": sum(score["extra_tool_calls"] for score in scores),
        "forbidden_tool_calls": sum(score["forbidden_tool_calls"] for score in scores),
        "repeated_tool_calls": sum(score["repeated_tool_calls"] for score in scores),
        "tool_budget_exceeded_count": sum(score["tool_budget_exceeded"] for score in scores),
        "citation_count": citations,
        "invalid_citation_count": citations - valid_citations,
        "citation_id_validity": valid_citations / citations if citations else None,
        "required_fact_exact_text_recall": sum(score["required_fact_exact_text_hits"] for score in scores) / facts if facts else None,
        "required_fact_support_id_coverage": sum(score["required_fact_support_id_hits"] for score in scores) / facts if facts else None,
        "error_cost_matrix": ERROR_COSTS,
        "invalid_action_cost": INVALID_ACTION_COST,
        "faithfulness_status": "UNCALIBRATED: pending 20 human labels; no faithfulness result claimed",
    }
