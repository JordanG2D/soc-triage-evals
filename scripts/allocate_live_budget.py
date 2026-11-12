"""Persist a nonrefundable $5 allocation before any paid request.

GitHub Contents API's expected SHA provides compare-and-swap. Concurrent or
ambiguous writes fail closed; no automatic retry can allocate a second lease.
Only metadata is written. Provider credentials never enter this script.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.request

from soc_triage.budget import ALLOCATION_MICRODOLLARS as ALLOCATION, MAX_CAP as CAP, validate_journal

REPOSITORY = "JordanG2D/soc-triage-evals"
PATH = ".budget/allocations.json"


def api(method: str, payload: dict | None = None) -> dict:
    token = os.environ["GH_TOKEN"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/contents/{PATH}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Live allocation is restricted to this repository's main-branch Actions workflow")
    run_id = os.environ["GITHUB_RUN_ID"] + ":" + os.environ["GITHUB_RUN_ATTEMPT"]
    remote = api("GET")
    journal = json.loads(base64.b64decode(remote["content"]))
    used = validate_journal(journal)
    if any(entry["run_id"] == run_id for entry in journal["allocations"]):
        raise ValueError("Run already allocated; refusing to reuse a potentially spent lease")
    if used + ALLOCATION > CAP:
        raise ValueError("Lifetime $20 allocation cap reached; no paid requests authorized")
    lease = {"run_id": run_id, "microdollars": ALLOCATION, "source_commit": os.environ["GITHUB_SHA"], "allocated_at": datetime.now(timezone.utc).isoformat()}
    journal["allocations"].append(lease)
    validate_journal(journal)
    result = api("PUT", {"message": "Reserve bounded live evaluation allocation\n\nCo-Authored-By: OpenAI Codex <noreply@openai.com>", "content": base64.b64encode((json.dumps(journal, indent=2) + "\n").encode()).decode(), "sha": remote["sha"], "branch": "main", "author": {"name": "Joshua Jordan", "email": "jordan@gen2dynamics.com"}, "committer": {"name": "Joshua Jordan", "email": "jordan@gen2dynamics.com"}})
    # Lease exists locally only after durable remote commit acknowledgement.
    lease["journal_commit"] = result["commit"]["sha"]
    validate_journal({"schema_version": 1, "cap_microdollars": CAP, "allocations": [lease]})
    destination = Path(".state/live-lease.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(lease, indent=2) + "\n")
    print(json.dumps({"allocation_usd": 5, "lifetime_allocated_usd": (used + ALLOCATION) / 1_000_000, "run_id": run_id, "journal_commit": lease["journal_commit"]}))


if __name__ == "__main__":
    main()
