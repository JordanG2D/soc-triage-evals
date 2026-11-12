"""Bounded Inspect tool-calling loop with injectable recorded and live adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import hashlib
from typing import Any, Protocol, Sequence

from inspect_ai.model import (
    ChatMessage, ChatMessageAssistant, ChatMessageSystem, ChatMessageUser,
    GenerateConfig, ModelOutput, ResponseSchema, execute_tools, get_model,
)
from inspect_ai.tool import Tool, ToolCall, ToolDef

from .prompts import SYSTEM_PROMPT, alert_prompt
from .schema import Alert, parse_decision
from .tools import ToolEnvironment
from .structured_output import SCHEMA_NAME, canonical_json, common_decision_schema, output_contract_metadata

MAX_TOOL_CALLS = 6
MAX_GENERATION_TURNS = 5
MAX_OUTPUT_TOKENS = 1024


class Adapter(Protocol):
    model_name: str

    async def generate(self, messages: list[ChatMessage], tools: Sequence[Tool], tool_choice: str) -> ModelOutput: ...


@dataclass
class AgentResult:
    alert_id: str
    raw_output: str
    decision: dict | None
    parse_error: str | None
    trace: list[dict]
    exposures: dict[str, dict]
    generation_count: int
    tool_calls: int
    stop_reason: str
    model: str
    messages: list[ChatMessage] = field(default_factory=list, repr=False)
    output: ModelOutput | None = field(default=None, repr=False)
    generations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            key: deepcopy(getattr(self, key))
            for key in (
                "alert_id", "raw_output", "decision", "parse_error", "trace", "exposures",
                "generation_count", "tool_calls", "stop_reason", "model", "generations",
            )
        }


class RecordedAdapter:
    """Replay prewritten assistant requests, never claim measured model quality."""

    model_name = "mock/recorded"

    def __init__(self, recording: dict):
        self.turns = deepcopy(recording["turns"])
        self.position = 0

    async def generate(self, messages: list[ChatMessage], tools: Sequence[Tool], tool_choice: str) -> ModelOutput:
        if self.position >= len(self.turns):
            raise ValueError("Recording ended before a final answer")
        turn = self.turns[self.position]
        self.position += 1
        calls = [
            ToolCall(
                id=call.get("id", f"recorded-{self.position}-{i}"),
                function=call["name"], arguments=call.get("arguments", {}),
            )
            for i, call in enumerate(turn.get("tool_calls", []))
        ]
        message = ChatMessageAssistant(content=turn.get("content", ""), tool_calls=calls or None, model=self.model_name)
        return ModelOutput.from_message(message, stop_reason="tool_calls" if calls else "stop")


class LiveInspectAdapter:
    """Every generation reserves budget before dispatch and settles observed usage."""

    def __init__(self, model: str, budget: Any):
        if not model.startswith(("openai/", "anthropic/")):
            raise ValueError("Live adapter supports explicit openai/ or anthropic/ model IDs")
        if budget is None:
            raise ValueError("Live generation requires a persistent budget ledger")
        self.model_name = model
        self.budget = budget
        self.response_schema = ResponseSchema(
            name=SCHEMA_NAME, json_schema=common_decision_schema(), strict=True,
        )
        self.provider_extra_body = (
            {"output_config": {"format": {"type": "json_schema", "schema": common_decision_schema()}}}
            if model.startswith("anthropic/") else {}
        )
        self.config = GenerateConfig(
            max_tokens=MAX_OUTPUT_TOKENS, max_retries=0, parallel_tool_calls=False,
            reasoning_effort="none" if model.startswith("openai/") else None,
            reasoning_summary="none" if model.startswith("openai/") else None,
            response_schema=self.response_schema if model.startswith("openai/") else None,
        )
        self.last_request_contract: dict | None = None
        model_args: dict[str, Any] = {"max_retries": 0, "streaming": False}
        if model.startswith("openai/"):
            model_args.update(responses_api=True, responses_store=False, service_tier="default")
        else:
            # Pinned Inspect's response_schema converter modifies scalar schema
            # nodes. Its provider-level extra_body reaches the current native
            # Messages format directly and preserves the shared grammar bytes.
            model_args["extra_body"] = self.provider_extra_body
        self._model = get_model(model, config=self.config, memoize=False, **model_args)

    async def generate(self, messages: list[ChatMessage], tools: Sequence[Tool], tool_choice: str) -> ModelOutput:
        # For text-only requests, one token cannot contain less than one UTF-8
        # byte. Include full tool schemas and a framing allowance rather than
        # dividing characters by a heuristic average token length.
        payload = {
            "messages": [message.model_dump(mode="json", exclude_none=True) for message in messages],
            "tools": [
                {
                    "name": definition.name, "description": definition.description,
                    "parameters": definition.parameters.model_dump(mode="json"),
                }
                for definition in (ToolDef(tool) for tool in tools)
            ],
            "response_schema": self.response_schema.model_dump(mode="json", by_alias=True, exclude_none=True),
            "provider_extra_body": self.provider_extra_body,
            "provider_format_metadata": {
                "type": "json_schema",
                **({"name": SCHEMA_NAME, "description": SCHEMA_NAME, "strict": True}
                   if self.model_name.startswith("openai/") else {}),
            },
        }
        contract = output_contract_metadata()
        contract.pop("schema")
        contract["message_text_sha256"] = hashlib.sha256(canonical_json([
            {"role": message.role, "content": message.model_dump(mode="json")["content"]}
            for message in messages
        ]).encode("utf-8")).hexdigest()
        contract["message_text_hash_scope"] = "role/content projection; excludes tool-call arguments and request headers"
        contract["tool_choice"] = tool_choice
        contract["provider_schema_route"] = (
            "responses.text.format" if self.model_name.startswith("openai/")
            else "messages.output_config.format"
        )
        self.last_request_contract = contract
        bound = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 8192
        if bound > 100_000:
            raise ValueError("Conservative request bound exceeds the configured input budget")
        reservation = self.budget.reserve(self.model_name, bound, MAX_OUTPUT_TOKENS, "triage")
        reservation_id = reservation.id if hasattr(reservation, "id") else reservation["id"]
        try:
            output = await self._model.generate(
                input=messages, tools=tools, tool_choice=tool_choice,
                config=self.config, cache=False,
            )
        except BaseException:
            self.budget.mark_uncertain(reservation_id)
            raise
        if output.usage is None:
            self.budget.mark_uncertain(reservation_id)
            raise RuntimeError("Provider returned no usage; reservation retained at its full bound")
        usage = output.usage
        self.budget.settle(
            reservation_id, usage.input_tokens, usage.output_tokens,
            cache_read_tokens=usage.input_tokens_cache_read or 0,
            cache_write_tokens=usage.input_tokens_cache_write or 0,
        )
        return output

    async def close(self) -> None:
        await self._model.api.client.close()


async def run_agent(alert: Alert | dict, adapter: Adapter, environment: ToolEnvironment) -> AgentResult:
    alert = Alert.model_validate(alert) if isinstance(alert, dict) else alert
    environment.reset(alert)
    messages: list[ChatMessage] = [
        ChatMessageSystem(content=SYSTEM_PROMPT), ChatMessageUser(content=alert_prompt(alert))
    ]
    tools = environment.inspect_tools()
    count = 0
    raw = ""
    output: ModelOutput | None = None
    stop_reason = "generation_limit"
    turn = 0
    generations: list[dict] = []
    for turn in range(1, MAX_GENERATION_TURNS + 1):
        final_turn = turn == MAX_GENERATION_TURNS or count == MAX_TOOL_CALLS
        if final_turn:
            messages.append(ChatMessageUser(content="The investigation budget is exhausted. Return the final JSON decision now."))
        output = await adapter.generate(messages, tools, "none" if final_turn else "auto")
        generations.append({
            "requested_model": adapter.model_name, "returned_model": output.model,
            "stop_reason": output.stop_reason,
            "usage": output.usage.model_dump(mode="json") if output.usage else None,
            "request_contract": deepcopy(getattr(adapter, "last_request_contract", None)),
        })
        messages.append(output.message)
        calls = output.message.tool_calls or []
        if not calls:
            raw = output.completion
            stop_reason = "final_answer"
            break
        if final_turn or count + len(calls) > MAX_TOOL_CALLS:
            stop_reason = "tool_limit" if count + len(calls) > MAX_TOOL_CALLS else "generation_limit"
            break
        count += len(calls)
        trace_start = len(environment.trace)
        results = await execute_tools(messages, tools, max_output=64 * 1024)
        messages.extend(results.messages)
        # Reconcile the trace against actual Inspect returns, including rejected
        # arguments and unknown tools. Error messages are observed context, but
        # never become citation sources or invented evidence facts.
        attempt_records: list[dict] = []
        for call in calls:
            response = next((
                message for message in results.messages
                if message.role == "tool" and message.tool_call_id == call.id
            ), None)
            if response is None:
                observed: Any = {"error": "No tool return was observed"}
                error: Any = "missing_tool_return"
            else:
                try:
                    observed = json.loads(response.text)
                except (ValueError, TypeError):
                    observed = {"text": response.text}
                error = asdict(response.error) if response.error else None
            attempt_records.append({
                "tool": call.function, "arguments": deepcopy(call.arguments),
                "call_id": call.id, "result": observed, "error": error,
            })
        environment.trace[trace_start:] = attempt_records
    decision, parse_error = parse_decision(raw)
    return AgentResult(
        alert.id, raw, decision.model_dump() if decision else None, parse_error,
        deepcopy(environment.trace), deepcopy(environment.exposures), turn, count,
        stop_reason, adapter.model_name, messages, output, generations,
    )


async def run_recorded(alert: Alert | dict, recording: dict, environment: ToolEnvironment) -> AgentResult:
    alert_id = alert.id if isinstance(alert, Alert) else alert["id"]
    if recording.get("alert_id") != alert_id:
        raise ValueError("Recording alert_id does not match the alert packet")
    return await run_agent(alert, RecordedAdapter(recording), environment)


async def run_live(
    alert: Alert | dict, model: str, environment: ToolEnvironment, budget: Any, prompt_version: str = "v1"
) -> AgentResult:
    if prompt_version != "v1":
        raise ValueError("Only prompt version v1 is implemented")
    adapter = LiveInspectAdapter(model, budget)
    try:
        return await run_agent(alert, adapter, environment)
    finally:
        await adapter.close()
