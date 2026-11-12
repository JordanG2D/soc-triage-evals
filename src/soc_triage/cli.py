"""One-command offline development validation and explicit human-review tools."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .judge import HumanReviewIncomplete, export_human_pack, judge_agreement, validate_human_labels
from .reporting import build_report, check_regression, write_report
from .scoring import score_case

CALIBRATION_ALERT_IDS = ("A002", "A004", "A005", "A007", "A009", "A010", "A011", "A012", "A013", "A014")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    with Path(path).open() as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def _load_directory(path: Path, id_field: str) -> dict[str, dict[str, Any]]:
    records = {}
    for source in sorted(path.glob("*.json")):
        record = json.loads(source.read_text())
        identifier = record[id_field]
        if identifier in records:
            raise ValueError(f"duplicate {id_field} in {path}: {identifier}")
        records[identifier] = record
    if not records:
        raise ValueError(f"no JSON cases found in {path}")
    return records


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run_offline(args: argparse.Namespace) -> int:
    from .agent import run_recorded
    from .retrieval import LocalRunbookIndex
    from .tools import ToolEnvironment

    started = time.monotonic()
    alerts = _load_directory(args.data_dir / "alerts", "id")
    references = _load_directory(args.data_dir / "references", "alert_id")
    recording_list = load_jsonl(args.recordings)
    recordings = {record["alert_id"]: record for record in recording_list}
    if len(recordings) != len(recording_list):
        raise ValueError("duplicate recording alert IDs")
    if alerts.keys() != references.keys() or alerts.keys() != recordings.keys():
        raise ValueError("alerts, references, and recordings must cover exactly the same cases; no missing or extra cases")
    if len(alerts) != 16:
        raise ValueError("this authorized development vertical slice requires exactly 16 alerts")
    if not args.model_dir.is_dir():
        raise ValueError(f"local embedding weights are required at {args.model_dir}; prepare them explicitly before running offline")
    # This loader receives a local path only: no implicit model download.
    retriever = LocalRunbookIndex.from_directory(args.runbooks_dir, args.model_dir)
    results, scores = [], []
    for alert_id in sorted(alerts):
        environment = ToolEnvironment(args.data_dir / "tool_context" / "context.json", retriever)
        result = (await run_recorded(alerts[alert_id], recordings[alert_id], environment)).to_dict()
        scores.append(score_case(references[alert_id], result))
        results.append({
            "alert": alerts[alert_id],
            "result": result,
            "provenance": {"execution_mode": "offline_fixture", "recording_sha256": _file_hash(args.recordings)},
        })
    from .scoring import aggregate_scores
    aggregate = aggregate_scores(scores)
    regression = {"status": "not_run", "reason": "No fixed baseline file was supplied."}
    if args.baseline is not None:
        expected = json.loads(args.baseline.read_text())
        regression = check_regression(aggregate, expected.get("metrics", expected))
    sources = sorted((args.data_dir / "alerts").glob("*.json")) + sorted((args.data_dir / "references").glob("*.json")) + sorted(args.runbooks_dir.glob("*.md")) + [args.recordings, args.data_dir / "tool_context" / "context.json"]
    metadata = {
        "cost_usd": 0,
        "fixture_wall_seconds": time.monotonic() - started,
        "source_hashes": {str(path): _file_hash(path) for path in sources},
        "responses": "Synthetic labeled development fixtures, not model-generated results.",
        "retrieval": "Local cached embedding weights; network-free runtime.",
    }
    report = build_report(scores, execution_mode="offline_fixture", metadata=metadata, regression=regression)
    write_report(report, args.output)
    (args.output / "records.jsonl").write_text("".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results))
    print(json.dumps({"status": regression["status"], "execution_mode": "offline_fixture", "case_count": len(scores), "cost_usd": 0, "report": str(args.output / "report.json"), "faithfulness": "UNCALIBRATED_PENDING_20_HUMAN_LABELS"}))
    return 1 if regression["status"] == "fail" else 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Synthetic SOC triage DEV evaluation; no operational claim")
    subcommands = command.add_subparsers(dest="command", required=True)
    offline = subcommands.add_parser("offline", help="Build local retrieval, run recorded fixtures, score, report, and check a fixed baseline")
    offline.add_argument("--data-dir", type=Path, default=Path("data"))
    offline.add_argument("--runbooks-dir", type=Path, default=Path("runbooks"))
    offline.add_argument("--recordings", type=Path, default=Path("recordings/dev_recorded.jsonl"))
    offline.add_argument("--model-dir", type=Path, default=Path(".cache/model2vec"))
    offline.add_argument("--output", type=Path, default=Path("artifacts/offline"))
    offline.add_argument("--baseline", type=Path, default=Path("baselines/offline.json"))
    live = subcommands.add_parser("live", help="Run the explicitly budgeted live development slice")
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--model-dir", type=Path, default=Path(".cache/model2vec"))
    live.add_argument("--ledger", type=Path, default=Path(".state/budget.sqlite3"))
    live.add_argument("--lease", type=Path, default=Path(".state/live-lease.json"))
    live.add_argument("--data-dir", type=Path, default=Path("data"))
    live.add_argument("--runbooks-dir", type=Path, default=Path("runbooks"))
    pack = subcommands.add_parser("export-human-pack", help="Export 20 actual live responses with all human labels blank")
    pack.add_argument("--records", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    agreement = subcommands.add_parser("judge-agreement", help="Refuse incomplete labels; report actual human/judge agreement")
    agreement.add_argument("--human-pack", type=Path, required=True)
    agreement.add_argument("--judgments", type=Path, required=True)
    agreement.add_argument("--output", type=Path, required=True)
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "offline":
            return asyncio.run(run_offline(args))
        if args.command == "live":
            from .live import run_live_slice
            return run_live_slice(args)
        if args.command == "export-human-pack":
            export_human_pack(load_jsonl(args.records), args.output, predeclared_alert_ids=CALIBRATION_ALERT_IDS)
            print(json.dumps({"status": "ready_for_human_review", "response_count": 20, "labels": "all_blank", "pack": str(args.output)}))
            return 0
        if args.command == "judge-agreement":
            pack = json.loads(args.human_pack.read_text())
            validate_human_labels(pack)
            judgments = json.loads(args.judgments.read_text())
            report = judge_agreement(pack, judgments)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report))
            return 0
    except HumanReviewIncomplete as exc:
        pending = {"status": "pending_human_labels", "agreement_rate": None, "error": str(exc)}
        if getattr(args, "output", None) is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(pending, indent=2) + "\n")
        print(json.dumps(pending), file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    return 2
