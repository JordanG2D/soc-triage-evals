"""Four deterministic, read-only tools over fictional context and local runbooks."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from inspect_ai.tool import Tool, tool

from .retrieval import LocalRunbookIndex
from .schema import Alert


class ToolEnvironment:
    """One sample's tool state and exactly the evidence exposed during that sample."""

    def __init__(self, context_path: str | Path | dict, retriever: LocalRunbookIndex):
        self.context = (
            deepcopy(context_path) if isinstance(context_path, dict)
            else json.loads(Path(context_path).read_text(encoding="utf-8"))
        )
        self.retriever = retriever
        self.trace: list[dict[str, Any]] = []
        self.exposures: dict[str, dict[str, Any]] = {}

    def reset(self, alert: Alert) -> None:
        self.trace.clear()
        self.exposures.clear()
        packet = alert.model_dump()
        self.exposures[f"alert:{alert.id}"] = {
            "source_id": f"alert:{alert.id}",
            "text": json.dumps(packet, sort_keys=True, ensure_ascii=False),
            "facts": _leaf_facts(packet),
        }

    def _record(self, name: str, arguments: dict, result: dict) -> str:
        # JSON is both the tool's actual model-visible return and the recorded
        # evidence. Recording never reads an evaluator reference file.
        content = json.dumps(result, sort_keys=True, ensure_ascii=False)
        if len(content.encode("utf-8")) > 48 * 1024:
            raise ValueError("Fixture return exceeds the allowed evidence size")
        self.trace.append({"tool": name, "arguments": arguments, "result": deepcopy(result)})
        if result.get("source_id"):
            self.exposures[result["source_id"]] = deepcopy(result)
        for hit in result.get("hits", []):
            self.exposures[hit["source_id"]] = deepcopy(hit)
        return content

    def lookup(self, name: str, key: str) -> str:
        if not isinstance(key, str) or not key or len(key) > 200:
            raise ValueError("Lookup key must contain 1–200 characters")
        category = self.context.get(name, {})
        item = category.get(key)
        if item is None:
            result = {
                "source_id": f"missing:{name}:{key}",
                "facts": [f"No fixture record is available for {key}."],
                "found": False,
            }
        else:
            result = deepcopy(item)
            if not isinstance(result.get("source_id"), str) or not isinstance(result.get("facts"), list):
                raise ValueError("Fixture record must provide source_id and facts")
            result["found"] = True
        argument = {"ip_reputation": "ip", "user_context": "user", "host_context": "host"}[name]
        return self._record(name, {argument: key}, result)

    def search(self, query: str, top_k: int = 3) -> str:
        result = {"hits": [hit.to_dict() for hit in self.retriever.search(query, top_k)]}
        return self._record("runbook_search", {"query": query, "top_k": top_k}, result)

    def inspect_tools(self) -> list[Tool]:
        return [ip_reputation(self), user_context(self), host_context(self), runbook_search(self)]


def _leaf_facts(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        return [fact for key, item in value.items() for fact in _leaf_facts(item, f"{prefix}.{key}".strip("."))]
    if isinstance(value, list):
        return [fact for item in value for fact in _leaf_facts(item, prefix)]
    return [f"{prefix}: {value}"]


@tool
def ip_reputation(environment: ToolEnvironment) -> Tool:
    async def execute(ip: str) -> str:
        """Look up a synthetic IP's frozen reputation observations.

        Args:
            ip: Source or destination IP address from the alert.
        """
        return environment.lookup("ip_reputation", ip)
    return execute


@tool
def user_context(environment: ToolEnvironment) -> Tool:
    async def execute(user: str) -> str:
        """Look up a fictional user's role, recent activity and approved changes.

        Args:
            user: Exact fictional user identifier from the alert.
        """
        return environment.lookup("user_context", user)
    return execute


@tool
def host_context(environment: ToolEnvironment) -> Tool:
    async def execute(host: str) -> str:
        """Look up a fictional host's purpose, baseline and nearby observations.

        Args:
            host: Exact fictional host identifier from the alert.
        """
        return environment.lookup("host_context", host)
    return execute


@tool
def runbook_search(environment: ToolEnvironment) -> Tool:
    async def execute(query: str, top_k: int = 3) -> str:
        """Retrieve local runbook passages using semantic embedding similarity.

        Args:
            query: A specific description of the suspicious behavior or question.
            top_k: Number of passages to return, between one and five.
        """
        return environment.search(query, top_k)
    return execute
