"""Honest reports distinguishing recorded mechanics from actual model runs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .scoring import aggregate_scores


def build_report(
    scores: Sequence[Mapping[str, Any]],
    *,
    execution_mode: str,
    metadata: Mapping[str, Any] | None = None,
    regression: Mapping[str, Any] | None = None,
    paired_comparison: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if execution_mode not in {"offline_fixture", "live_model"}:
        raise ValueError("execution_mode must explicitly identify fixtures or actual model responses")
    details = dict(metadata or {})
    if execution_mode == "offline_fixture":
        details["cost_usd"] = 0
        # Never promote fixture runtime into provider/model latency.
        if "model_latency_seconds" in details:
            raise ValueError("fixture wall time is not model latency")
    return {
        "schema_version": 1,
        "execution_mode": execution_mode,
        "evaluation_scope": "synthetic DEV vertical slice; all 16 alerts are development material, not a formal test set",
        "metrics": aggregate_scores(scores),
        "cases": list(scores),
        "metadata": details,
        "regression": dict(regression) if regression is not None else {"status": "not_run"},
        "paired_comparison": dict(paired_comparison) if paired_comparison is not None else {"status": "pending_actual_paired_configurations"},
        "faithfulness_judge": {"status": "UNCALIBRATED_PENDING_20_HUMAN_LABELS", "agreement_rate": None},
        "frozen_comparison": {"status": "not_started", "reason": "Full dataset and frozen comparison are outside this development slice."},
        "limitations": [
            "Synthetic development cases do not establish operational SOC performance or a ship decision.",
            "Recorded fixture responses verify plumbing and deterministic scoring; they are not model results.",
            "Citation ID validity, exact fact text, and source ID coverage are mechanical checks, not semantic faithfulness.",
            "Error costs are a predeclared illustrative triage policy, not measured business losses.",
            "Severity MAE excludes invalid severities; its valid denominator is reported, while all-case accuracy retains failures.",
            "No faithfulness agreement is claimed before 20 actual human labels and corresponding judge outputs exist.",
            "Do not tune on a frozen test set; none is introduced by this DEV slice.",
        ],
    }


def findings_markdown(report: Mapping[str, Any]) -> str:
    metrics = report["metrics"]
    fixture = report["execution_mode"] == "offline_fixture"
    title = "Offline fixture validation" if fixture else "Live synthetic development evaluation"
    mode = (
        "These numbers describe deterministic recorded-response fixtures and locally executed synthetic tools. They do not measure a model's triage performance. Fixture API cost is $0; any fixture elapsed time is local harness time, not model latency."
        if fixture else
        "These numbers describe actual model responses on a small synthetic development slice. Billing and timing evidence must come from the live run metadata. They do not establish operational SOC performance."
    )
    mae = metrics["severity_mae"]
    citations = metrics["citation_id_validity"]
    lines = [
        f"# {title}", "", mode, "",
        "All 16 alerts belong to DEV. No full dataset or frozen comparison has been run.", "",
        "| Measure | Observed value |", "| --- | --- |",
        f"| Scored cases | {metrics['case_count']} |",
        f"| Expected triage-action accuracy | {metrics['verdict_accuracy']:.3f} |",
        f"| Mean illustrative error cost | {metrics['mean_error_cost']:.3f} |",
        f"| Always-escalate mean error cost | {metrics['always_escalate_mean_error_cost']:.3f} |",
        f"| Always-escalate action accuracy | {metrics['always_escalate_verdict_accuracy']:.3f} |",
        f"| False-benign decisions on malicious events | {metrics['false_benign_on_malicious_count']} / {metrics['malicious_case_count']} |",
        f"| Invalid outputs | {metrics['invalid_output_count']} |",
        f"| Exact / within-one severity accuracy | {metrics['severity_exact_accuracy']:.3f} / {metrics['severity_within_one_accuracy']:.3f} |",
        f"| Severity MAE (valid denominator) | {mae if mae is not None else 'unavailable'} ({metrics['severity_mae_valid_count']}) |",
        f"| Acceptable ATT&CK technique accuracy | {metrics['technique_accuracy']:.3f} |",
        f"| Mean required-tool alternative coverage | {metrics['mean_tool_requirement_coverage']:.3f} |",
        f"| Extra / forbidden tool calls | {metrics['extra_tool_calls']} / {metrics['forbidden_tool_calls']} |",
        f"| Citation ID validity | {f'{citations:.3f}' if citations is not None else 'unavailable (no citations)'} |",
        "", "Expected triage action and event truth are separate: an unknown event may correctly require escalation. The predeclared event-truth cost matrix is preserved in report.json; a benign decision on a malicious event has the largest valid-action cost (10). Invalid actions also cost 10.",
        "", "Citation IDs only establish that a source was actually exposed. A valid ID does not prove that its cited claim follows from that source. Fact-text recall and source coverage are likewise mechanical.",
        "", f"Regression status: {report['regression'].get('status', 'unknown')}.",
        "", "Faithfulness judge: **UNCALIBRATED — pending 20 human labels**. No human labels, judge labels, or agreement are fabricated. Export 20 actual live responses with blank labels, then obtain the human review before running the judge.",
        "", "Paired uncertainty is computed only for actual matched configurations by resampling whole alert families. Missing pairs or unscored values are errors; a single configuration has no paired interval.",
        "", "Limits: this development harness supports inspection and regression work. It does not establish a ship decision, operational SOC readiness, or frozen-test performance.", "",
    ]
    paired = report.get("paired_comparison", {})
    if paired.get("status") == "observed_dev_comparison":
        lines.extend([
            "Exploratory actual paired DEV comparison (candidate minus baseline):",
            f"Baseline: `{paired['baseline_model']}`; candidate: `{paired['candidate_model']}`.",
            "",
        ])
        for metric, estimate in paired["metrics"].items():
            lower, upper = estimate["interval"]
            lines.append(f"- {metric}: mean difference {estimate['mean_difference']:.4f}, {estimate['confidence_level']:.0%} family-bootstrap interval [{lower:.4f}, {upper:.4f}], {estimate['case_count']} matched alerts in {estimate['family_count']} families.")
        lines.extend(["", "Lower error cost and higher action accuracy are preferable. These intervals use 32 actual responses on the same 16 DEV alerts. They are exploratory with few synthetic families and do not constitute the frozen comparison.", ""])
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], directory: str | Path) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (directory / "FINDINGS.md").write_text(findings_markdown(report))


def check_regression(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    """Compare explicit fixed expectations; absent keys fail instead of vanish."""
    mismatches = []
    def compare(observed: Any, target: Any, key: str) -> None:
        if isinstance(target, Mapping):
            if not isinstance(observed, Mapping):
                mismatches.append({"field": key, "expected": target, "actual": observed})
                return
            for child, value in target.items():
                if child not in observed:
                    mismatches.append({"field": f"{key}.{child}", "expected": value, "actual": "<missing>"})
                else:
                    compare(observed[child], value, f"{key}.{child}".lstrip("."))
        elif observed != target:
            mismatches.append({"field": key, "expected": target, "actual": observed})
    compare(actual, expected, "")
    return {"status": "pass" if not mismatches else "fail", "mismatches": mismatches, "scope": "recorded fixture regression only; not model evaluation"}
