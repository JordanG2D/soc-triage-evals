"""One shared native output grammar; complete validation remains local."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .prompts import SYSTEM_PROMPT
from .schema import Decision

OUTPUT_PROTOCOL = "native-json-schema-v1"
SCHEMA_NAME = "triage_decision"
SCHEMA_DESCRIPTION = "Synthetic SOC triage decision with observed evidence citations."

# Provider grammar subsets differ. Apply one relaxation to BOTH providers, then
# validate the original constraints with the unchanged strict Decision model.
_LOCAL_ONLY_CONSTRAINTS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format", "minItems", "maxItems", "uniqueItems",
})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def common_decision_schema() -> dict:
    original = Decision.model_json_schema()
    definitions = original.get("$defs", {})

    def relax(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                reference = value["$ref"]
                if not reference.startswith("#/$defs/") or reference.removeprefix("#/$defs/") not in definitions:
                    raise ValueError("Unsupported response schema reference")
                resolved = deepcopy(definitions[reference.removeprefix("#/$defs/")])
                resolved.update({key: item for key, item in value.items() if key != "$ref"})
                return relax(resolved)
            return {
                key: relax(item) for key, item in value.items()
                if key not in _LOCAL_ONLY_CONSTRAINTS and key not in {"$defs", "title"}
            }
        if isinstance(value, list):
            return [relax(item) for item in value]
        return value

    schema = relax(deepcopy(original))
    schema["description"] = SCHEMA_DESCRIPTION
    schema["properties"]["severity"]["enum"] = [1, 2, 3, 4]
    return schema


def output_contract_metadata() -> dict:
    schema = common_decision_schema()
    return {
        "protocol": OUTPUT_PROTOCOL,
        "schema_name": SCHEMA_NAME,
        "schema_description": SCHEMA_DESCRIPTION,
        "schema_sha256": hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "schema": schema,
        "local_validation": "Decision strict validation; no fence stripping or answer repair",
        "local_only_constraints": sorted(_LOCAL_ONLY_CONSTRAINTS),
    }
