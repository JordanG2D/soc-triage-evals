"""Run the authorized 16-alert, one-prompt development slice on two providers."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import urllib.request

from .budget import BudgetLedger, MODELS, validate_journal, INPUT_MICRODOLLARS, OUTPUT_MICRODOLLARS
from .cli import CALIBRATION_ALERT_IDS, _load_directory
from .judge import export_human_pack
from .reporting import build_report, write_report
from .inspect_task import run_live_task_sync
from .scoring import score_case
from .statistics import paired_family_bootstrap

REPOSITORY = "JordanG2D/soc-triage-evals"


def verified_lease(path: Path) -> dict:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Paid execution requires this repository's main-branch manual workflow")
    lease = json.loads(path.read_text())
    validate_journal({"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [lease]})
    expected_run = os.environ["GITHUB_RUN_ID"] + ":" + os.environ["GITHUB_RUN_ATTEMPT"]
    if lease.get("run_id") != expected_run or lease.get("source_commit") != os.environ["GITHUB_SHA"] or lease.get("microdollars") != 5_000_000:
        raise ValueError("Lease does not match the current run, source, and bounded allocation")
    commit = lease.get("journal_commit", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Invalid durable allocation commit")
    request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/contents/.budget/allocations.json?ref={commit}", headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + os.environ["GH_TOKEN"]})
    journal = json.loads(base64.b64decode(json.load(urllib.request.urlopen(request, timeout=30))["content"]))
    validate_journal(journal)
    matching = [entry for entry in journal.get("allocations", []) if entry.get("run_id") == expected_run]
    if matching != [{key: value for key, value in lease.items() if key != "journal_commit"}] or journal.get("cap_microdollars") != 20_000_000 or sum(e["microdollars"] for e in journal["allocations"]) > 20_000_000:
        raise ValueError("Lease missing from the durable lifetime allocation journal")
    return lease


def estimated_standard_cost(result: dict) -> float:
    # Inspect exposes uncached, cache-read, cache-write token categories separately.
    # Cache writes use a conservative 1h Anthropic price when duration is absent.
    rates = (Decimal("0.10"), Decimal("0.01"), Decimal("0.125"), Decimal("0.50")) if result["model"].startswith("openai/") else (Decimal("1"), Decimal("0.1"), Decimal("2"), Decimal("5"))
    total = Decimal(0)
    for generation in result["generations"]:
        usage = generation.get("usage") or {}
        counts = (usage.get("input_tokens", 0), usage.get("input_tokens_cache_read") or 0, usage.get("input_tokens_cache_write") or 0, usage.get("output_tokens", 0))
        total += sum(Decimal(count) * rate for count, rate in zip(counts, rates)) / 1_000_000
    return float(total)


def run_live_slice(args) -> int:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(name):
            raise ValueError(f"Missing required secret {name}; no model requests sent")
    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
        if os.environ.get(name):
            raise ValueError(f"Unexpected provider routing override {name}; no requests sent")
    lease = verified_lease(args.lease)
    ledger = BudgetLedger(args.ledger, Decimal(lease["microdollars"]) / 1_000_000, lease_id=lease["run_id"])
    if ledger.snapshot()["charged_upper_microdollars"] != 0 or (args.output / "records.jsonl").exists():
        raise ValueError("This run already has spending or response evidence; refusing an implicit replay")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    model_scores = {}
    model_reports = {}
    alerts = _load_directory(args.data_dir / "alerts", "id")
    if len(alerts) != 16:
        raise ValueError("Only the 16-alert development slice is authorized")
    references = _load_directory(args.data_dir / "references", "alert_id")
    if references.keys() != alerts.keys():
        raise ValueError("Alert/reference coverage mismatch")
    inputs = sorted(args.data_dir.rglob("*.json")) + sorted(args.runbooks_dir.glob("*.md")) + [Path("config/embedding.json")]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    try:
        for model in MODELS:
            scores = []
            batch = run_live_task_sync(
                model, ledger, data_dir=str(args.data_dir), runbooks_dir=str(args.runbooks_dir),
                model_path=str(args.model_dir), log_dir=str(args.output / "inspect" / model.split("/")[0]),
            )
            if {result["alert_id"] for result in batch} != alerts.keys() or len(batch) != 16:
                raise ValueError("Inspect did not return all 16 development responses")
            for result in batch:
                alert_id = result["alert_id"]
                alert = alerts[alert_id]
                elapsed = result.pop("latency_seconds")
                accounting = sum(
                    (usage["input_tokens"] + (usage.get("input_tokens_cache_read") or 0) + (usage.get("input_tokens_cache_write") or 0)) * INPUT_MICRODOLLARS + usage["output_tokens"] * OUTPUT_MICRODOLLARS
                    for generation in result["generations"] for usage in [generation["usage"]]
                )
                estimate = estimated_standard_cost(result)
                record = {"alert": alert, "result": result, "provenance": {"execution_mode": "live_model", "run_id": lease["run_id"], "source_commit": lease["source_commit"], "journal_commit": lease["journal_commit"], "model": model, "prompt_version": "v1", "timestamp": datetime.now(timezone.utc).isoformat(), "end_to_end_response_latency_seconds": elapsed, "latency_scope": "Wall time for all provider generations, local tool execution, and parsing for this alert.", "estimated_standard_cost_usd": estimate, "cost_upper_microdollars": accounting, "input_sha256": hashes}}
                records.append(record)
                with (args.output / "records.jsonl").open("a") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                score = score_case(references[alert_id], result)
                score.update(end_to_end_response_latency_seconds=elapsed, estimated_standard_cost_usd=estimate)
                scores.append(score)
                print(json.dumps({"model": model, "alert": alert_id, "completed": len(records), "parse_ok": result["decision"] is not None}), flush=True)
            selected = [r for r in records if r["result"]["model"] == model]
            metadata = {"model": model, "prompt_version": "v1", "source_commit": lease["source_commit"], "run_id": lease["run_id"], "estimated_standard_cost_usd": sum(r["provenance"]["estimated_standard_cost_usd"] for r in selected), "end_to_end_response_latency_seconds": [r["provenance"]["end_to_end_response_latency_seconds"] for r in selected], "latency_scope": "Wall time for all provider generations, local tool execution, and parsing per alert; not isolated generation latency.", "billing": "Token-based standard-price estimate; invoice not retrieved. Conservative budget ledger separately charges a higher ceiling.", "budget": ledger.snapshot()}
            model_scores[model] = scores
            model_reports[model] = build_report(scores, execution_mode="live_model", metadata=metadata)
            write_report(model_reports[model], args.output / model.split("/")[0])
        baseline_model, candidate_model = tuple(MODELS)
        paired = {
            "status": "observed_dev_comparison",
            "scope": "Exploratory paired model comparison on the same 16 synthetic DEV alerts (32 actual responses); not the frozen comparison.",
            "baseline_model": baseline_model,
            "candidate_model": candidate_model,
            "metrics": {
                metric: paired_family_bootstrap(model_scores[baseline_model], model_scores[candidate_model], metric=metric, expected_alert_ids=sorted(alerts))
                for metric in ("error_cost", "verdict_correct")
            },
        }
        (args.output / "paired-dev-comparison.json").write_text(json.dumps(paired, indent=2) + "\n")
        for model, report in model_reports.items():
            report["paired_comparison"] = paired
            write_report(report, args.output / model.split("/")[0])
        export_human_pack(records, args.output / "human-calibration.json", predeclared_alert_ids=CALIBRATION_ALERT_IDS)
        print(json.dumps({"status": "vertical_slice_complete", "live_responses": len(records), "human_responses": 20, "judge_status": "pending_human_labels", "budget": ledger.snapshot()}))
        return 0
    finally:
        (args.output / "budget.json").write_text(json.dumps(ledger.snapshot(), indent=2) + "\n")
