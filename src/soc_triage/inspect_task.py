"""Inspect task entry point for the sixteen-case development vertical slice."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver

from .agent import run_live, run_recorded
from .prompts import alert_prompt
from .retrieval import LocalRunbookIndex
from .schema import Alert
from .tools import ToolEnvironment


@solver
def recorded_triage_solver(
    context_path: str, runbooks_dir: str, model_path: str, recordings_path: str
) -> Solver:
    """Replay assistant requests through actual Inspect tools, with bounded turns."""

    index = LocalRunbookIndex.from_directory(runbooks_dir, model_path)
    recordings = {
        record["alert_id"]: record
        for line in Path(recordings_path).read_text(encoding="utf-8").splitlines()
        if line.strip() for record in [json.loads(line)]
    }

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        packet = state.metadata["alert"]
        environment = ToolEnvironment(context_path, index)
        result = await run_recorded(packet, recordings[packet["id"]], environment)
        state.messages = result.messages
        if result.output is not None:
            state.output = result.output
        state.metadata["triage_result"] = result.to_dict()
        return state

    return solve


@scorer(metrics=[accuracy()])
def triage_score(references_dir: str) -> Scorer:
    """Load event truth only at scoring time, outside model and tool context."""

    async def score(state: TaskState, target: Target) -> Score:
        from .scoring import score_case

        alert_id = state.metadata["alert"]["id"]
        reference = json.loads((Path(references_dir) / f"{alert_id}.json").read_text(encoding="utf-8"))
        details = score_case(reference, state.metadata["triage_result"])
        return Score(value=int(details["verdict_correct"]), metadata=details)

    return score


@task
def soc_triage(
    data_dir: str = "data", runbooks_dir: str = "runbooks",
    model_path: str = ".cache/model2vec", recordings_path: str = "recordings/dev_recorded.jsonl",
) -> Task:
    """Offline recorded mechanics evaluation; these scores are not model quality."""

    root = Path(data_dir)
    alerts = [Alert.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted((root / "alerts").glob("*.json"))]
    if not alerts or len(alerts) > 16:
        raise ValueError("This development slice requires one to sixteen alert packets")
    return Task(
        dataset=[
            Sample(id=alert.id, input=alert_prompt(alert), metadata={"alert": alert.model_dump()})
            for alert in alerts
        ],
        solver=recorded_triage_solver(
            str(root / "tool_context" / "context.json"), runbooks_dir, model_path, recordings_path
        ),
        scorer=triage_score(str(root / "references")),
        model="mockllm/model",
        message_limit=30,
    )


def run_live_task_sync(
    model: str, ledger: Any, data_dir: str = "data", runbooks_dir: str = "runbooks",
    model_path: str = ".cache/model2vec", log_dir: str = "artifacts/inspect",
) -> list[dict]:
    """Run one live development condition inside an actual Inspect evaluation.

    The outer mock model performs no generations. The custom solver calls the
    requested provider exclusively through the reservation-guarded live adapter.
    Provider events, messages, tools, scoring and results enter the native log.
    """

    root = Path(data_dir)
    index = LocalRunbookIndex.from_directory(runbooks_dir, model_path)
    packets = [
        Alert.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((root / "alerts").glob("*.json"))
    ]
    if not packets or len(packets) > 16:
        raise ValueError("This development slice requires one to sixteen alert packets")

    @solver
    def bounded_live() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            environment = ToolEnvironment(root / "tool_context" / "context.json", index)
            started = perf_counter()
            result = await run_live(state.metadata["alert"], model, environment, ledger)
            elapsed = perf_counter() - started
            state.messages = result.messages
            if result.output is not None:
                state.output = result.output
            state.metadata["triage_result"] = {**result.to_dict(), "latency_seconds": elapsed}
            return state
        return solve

    task_instance = Task(
        dataset=[Sample(id=packet.id, input=alert_prompt(packet), metadata={"alert": packet.model_dump()}) for packet in packets],
        solver=bounded_live(), scorer=triage_score(str(root / "references")),
        model="mockllm/model", message_limit=30,
        metadata={"mode": "live_development", "condition": model, "prompt_version": "v1"},
    )
    logs = eval(
        task_instance, log_dir=log_dir, log_format="json", display="none",
        max_samples=1, max_tasks=1, fail_on_error=True, continue_on_fail=False,
        retry_on_error=0, ctl_server=False, acp_server=False, log_model_api=False,
        max_retries=0,
    )
    results: list[dict] = []
    for log in logs:
        if log.status != "success" or any(sample.error for sample in log.samples or []):
            raise RuntimeError("Inspect live evaluation did not complete successfully; inspect the native log")
        for sample in log.samples or []:
            result = sample.metadata["triage_result"]
            result["inspect_log"] = str(log.location)
            results.append(result)
    return sorted(results, key=lambda result: result["alert_id"])
