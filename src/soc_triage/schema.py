"""Public input and output contracts for synthetic alert triage."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Process(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    command_line: str
    parent: str


class Alert(BaseModel):
    """The model-visible packet; references are deliberately a separate input."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^A\d{3}$")
    family_id: str
    source: str
    rule: str
    host: str
    user: str
    source_ip: str
    destination_ip: str
    process: Process
    timestamp: str
    event: dict[str, Any]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(min_length=1, max_length=160)
    fact: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["true_positive", "benign", "needs_escalation"]
    severity: int = Field(ge=1, le=4, description="1 is highest severity")
    technique_id: str | None = Field(pattern=r"^T\d{4}(?:\.\d{3})?$")
    summary: str = Field(min_length=1, max_length=3000)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=12)


def parse_decision(raw_output: str) -> tuple[Decision | None, str | None]:
    """Accept one JSON object, never repair or silently coerce a model answer."""

    try:
        payload = json.loads(raw_output)
        return Decision.model_validate(payload), None
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
