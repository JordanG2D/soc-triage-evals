"""Offline transport-schema and unchanged local-validation contract checks.

No providers, responses, scenario truth or human faithfulness labels are used.
Wire serialization is exercised separately by the provider transport tests.
"""

from copy import deepcopy
import hashlib
import json

from jsonschema import Draft202012Validator
import pytest
from inspect_ai.model import ResponseSchema
from inspect_ai.util._json import json_schema_dump

from soc_triage.prompts import SYSTEM_PROMPT
from soc_triage.schema import Decision, parse_decision
from soc_triage.structured_output import common_decision_schema, output_contract_metadata


OFFLINE_DECISION = {
    "verdict": "needs_escalation", "severity": 3, "technique_id": None,
    "summary": "Offline schema-validation example only, not a scenario assessment.",
    "evidence": [{"source_id": "offline:test", "fact": "This is an offline schema example."}],
}
RELAXED_LIMIT_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                      "multipleOf", "minLength", "maxLength", "pattern", "minItems", "maxItems"}


def nested_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


def test_shared_transport_structure_has_required_nullable_fields_and_closed_objects():
    schema = common_decision_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(OFFLINE_DECISION)
    assert schema["properties"]["severity"]["enum"] == [1, 2, 3, 4]
    assert set(schema["properties"]["verdict"]["enum"]) == {"true_positive", "benign", "needs_escalation"}
    evidence = schema["properties"]["evidence"]["items"]
    assert evidence["type"] == "object"
    assert evidence["additionalProperties"] is False
    assert set(evidence["required"]) == {"source_id", "fact"}
    assert not RELAXED_LIMIT_KEYS.intersection(nested_keys(schema))
    assert Draft202012Validator(schema).is_valid(OFFLINE_DECISION)
    missing_nullable = deepcopy(OFFLINE_DECISION)
    del missing_nullable["technique_id"]
    assert not Draft202012Validator(schema).is_valid(missing_nullable)


def test_schema_generation_does_not_mutate_the_full_local_contract():
    original = deepcopy(Decision.model_json_schema())
    first = common_decision_schema()
    first["properties"]["severity"]["enum"].append(99)
    first["properties"]["evidence"]["items"]["required"].clear()
    second = common_decision_schema()
    assert second["properties"]["severity"]["enum"] == [1, 2, 3, 4]
    assert set(second["properties"]["evidence"]["items"]["required"]) == {"source_id", "fact"}
    assert Decision.model_json_schema() == original


def test_canonical_schema_survives_inspect_conversion_without_silent_field_loss():
    schema = common_decision_schema()
    converted = ResponseSchema(name="offline_schema_contract", json_schema=schema, strict=True)
    assert json_schema_dump(converted.json_schema) == schema
    assert "$ref" not in set(nested_keys(schema))
    assert "$defs" not in set(nested_keys(schema))


@pytest.mark.parametrize("change", ["empty-summary", "long-summary", "empty-evidence", "long-evidence",
                                         "empty-source", "long-source", "empty-fact", "long-fact", "bad-technique"])
def test_looser_transport_never_weakens_strict_local_validation(change):
    payload = deepcopy(OFFLINE_DECISION)
    if change == "empty-summary":
        payload["summary"] = ""
    elif change == "long-summary":
        payload["summary"] = "x" * 3001
    elif change == "empty-evidence":
        payload["evidence"] = []
    elif change == "long-evidence":
        payload["evidence"] *= 13
    elif change == "empty-source":
        payload["evidence"][0]["source_id"] = ""
    elif change == "long-source":
        payload["evidence"][0]["source_id"] = "x" * 161
    elif change == "empty-fact":
        payload["evidence"][0]["fact"] = ""
    elif change == "long-fact":
        payload["evidence"][0]["fact"] = "x" * 2001
    else:
        payload["technique_id"] = "not-a-technique-id"
    # The same deliberately relaxed grammar can be sent to both providers;
    # the original business constraints remain strict and are never repaired.
    assert Draft202012Validator(common_decision_schema()).is_valid(payload)
    decision, error = parse_decision(json.dumps(payload))
    assert decision is None
    assert error is not None


@pytest.mark.parametrize("severity", [True, "3", 0, 5])
def test_severity_type_and_enum_are_enforced_in_both_contracts(severity):
    payload = {**OFFLINE_DECISION, "severity": severity}
    assert not Draft202012Validator(common_decision_schema()).is_valid(payload)
    assert parse_decision(json.dumps(payload))[0] is None


@pytest.mark.parametrize("severity", [1, 2, 3, 4])
def test_all_four_integer_severities_still_validate(severity):
    payload = {**OFFLINE_DECISION, "severity": severity}
    assert Draft202012Validator(common_decision_schema()).is_valid(payload)
    decision, error = parse_decision(json.dumps(payload))
    assert error is None and decision.severity == severity


@pytest.mark.parametrize("nested", [False, True])
def test_unknown_fields_rejected_in_both_contracts(nested):
    payload = deepcopy(OFFLINE_DECISION)
    target = payload["evidence"][0] if nested else payload
    target["unexpected_field"] = "offline example"
    assert not Draft202012Validator(common_decision_schema()).is_valid(payload)
    assert parse_decision(json.dumps(payload))[0] is None


@pytest.mark.parametrize("wrapper", ["```json\n{}\n```", "Here is the answer: {}"])
def test_text_fences_and_prose_remain_invalid_without_posthoc_repair(wrapper):
    raw = wrapper.format(json.dumps(OFFLINE_DECISION))
    decision, error = parse_decision(raw)
    assert decision is None and error is not None


def test_output_contract_metadata_binds_stable_schema_and_unchanged_visible_prompt():
    metadata = output_contract_metadata()
    assert metadata["protocol"] == "native-json-schema-v1"
    assert metadata["schema"] == common_decision_schema()
    canonical = json.dumps(metadata["schema"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert metadata["schema_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert metadata["system_prompt_sha256"] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    assert output_contract_metadata() == metadata
