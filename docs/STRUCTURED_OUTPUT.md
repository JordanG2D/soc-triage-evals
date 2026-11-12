# Structured output repair protocol

This protocol was declared before the repair run. The project owner requested investigation of the 16 first-run Haiku format failures, equivalent structured-output support for both providers, and a rerun of the same development slice. Dataset expansion and the frozen test remain outside this work.

## What was wrong

Run 1 asked for JSON in the application prompt and parsed the complete returned text strictly. Neither provider received an enforced response schema. Haiku produced seven analysis-prefixed fenced answers and nine directly fenced answers. The parser correctly rejected the wrappers under that contract. This is an observed instruction/serialization failure in the prompt-only condition; it does not establish 16 independent investigation failures or a general model-quality ranking.

The same initial system instructions, alert packets and tool definitions were recorded for both providers. Later histories differed because the models chose different tools and stopped at different times. Inspect also serializes disabled final tools differently: OpenAI omits definitions; Anthropic retains them with tool use disabled. This API-specific context difference is documented rather than hidden or rewritten into a different history.

The harness configuration omitted available native schema enforcement for both providers. The repair supplies equivalent enforcement before generation; it does not strip fences after generation or rescore the first run. See the [three full raw responses and native-log audit](format-investigation-run1.md).

## Shared output contract

Both models receive the same canonical JSON schema on every generation, including turns where they may call an investigation tool and the final turn with tool choice disabled. The schema constrains required keys, types, verdict/severity enums, nullable technique ID, and closed nested evidence objects.

The transport schema uses a shared supported subset. String lengths, numerical bounds, array bounds, technique pattern and related local constraints are removed symmetrically for both providers; severity is instead constrained with an integer enum of 1 through 4. References are inlined because Inspect's schema representation otherwise drops Pydantic definitions, and dropped title annotations are removed before hashing. The original strict `Decision` model still validates all fields and limits after generation. An output that violates local validation remains a failure.

The protocol is `native-json-schema-v1`. The canonical schema and SHA-256, unchanged system-prompt hash, route and request metadata are retained in the repaired run. Transport tests inspect actual HTTP request JSON produced by the real pinned SDKs and Inspect converters with an offline mock server; they do not call paid models.

| Provider | Native schema route |
| --- | --- |
| OpenAI Responses | `text.format`, JSON schema, `strict: true` |
| Anthropic Messages | Current native `output_config.format` JSON schema, supplied through the provider-level request body |

The pinned Inspect version's Anthropic `response_schema` path uses a legacy beta parameter and injects additional-properties keywords into non-object schema nodes. Its `GenerateConfig.extra_body` path silently filters `output_config`. The repair therefore uses the tested provider-level `get_model(..., extra_body=...)` request path for Anthropic's current GA `output_config.format` field, while OpenAI uses Inspect's normal `response_schema` mapping. Wire tests require the actual transmitted schema dictionaries and their hashes to match exactly, including nested evidence. Neither a flag's name nor a schema in application memory is taken as proof that the provider received it. See [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Anthropic structured outputs and migration](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), and [Inspect structured output](https://inspect.aisi.org.uk/structured.html).

Native enforcement is not a guarantee of factual correctness. Refusals, truncations, or local constraint failures remain possible and are retained without repair. The original prompt, alerts, references, retrieval assets, scorer, models, six-call tool budget, five-generation limit, and 1,024-output-token limit are unchanged.

## Unrecorded capability probe

The pinned OpenAI provider attempts to detect reasoning-summary support when `reasoning_summary` is unset. It can send a separate `responses.create` request asking for a greeting before the requested generation. That probe omits an output-token limit and its usage is not returned in the triage generation's usage. Its cache is per provider instance; the original agent constructed a fresh instance per alert. Transient probe failures can leave the cache unset.

Offline request capture reproduces this behavior for the historical configuration. It proves the code path, not the exact number or billing outcome of requests in the earlier live run: exact HTTP logs and an account invoice were not retained. The original $0.187791765 figure is therefore a **recorded-triage-generation token estimate**, excluding unresolved probe usage; it must not be presented as the complete bill. The original records and budget summary remain unaltered as historical evidence.

The repair explicitly sets OpenAI `reasoning_summary="none"`. Request-bound tests include the schema, check one SDK request per reservation, and exercise ordinary and tool-disabled turns for both providers. Model and SDK retries remain zero. No paid capability probes or extra live smoke tests are part of the rerun.

## Rerun and interpretation

Run 2 repeats all 16 development cases on both models with one unchanged prompt. It receives a new nonrefundable $5 workflow allocation under the lifetime $20 journal, bringing recorded allocations to $10 when granted. Costs are reported separately by run; historical unrecorded usage remains an explicit reconciliation limit.

The predeclared human-calibration case IDs remain the same ten per model, with the repaired run's new 20-response pack left blank. No coding agent or judge supplies human labels. Original calibration materials stay preserved.

Both runs belong in `FINDINGS.md`. Any before/after changes are development observations under a changed output protocol, not a clean causal ablation: sampling trajectories, grammar effects and removed probe overhead can also change costs, latency and downstream answers. GPT-6 Luna's original 16/16 agreement with these 16 authored development labels is **not evidence of model quality or a shipping recommendation**. The full frozen family-held-out test and human-calibrated faithfulness evaluation are still needed.
