# Output-format investigation and two development runs

This project pairs an AI security-alert agent with an evaluation system that scores decisions, runs automated checks, and preserves evidence. The first run exposed a harness gap: Haiku wrapped all 16 answers in Markdown and failed the required JSON format. We fixed the harness to enforce the same JSON schema for both providers and reran the slice while preserving the original evidence. Each model then returned 16 valid outputs but matched only 15 reference decisions, with additional severity and technique errors and unnecessary tool calls. Real-world SOC performance and whether every explanation is supported by its evidence remain unvalidated.

**Engineering portfolio status: complete for the authorized 16-alert slice.** Semantic faithfulness calibration is pending—not failed or completed—and is optional research rather than a completion gate. Joshua’s role is evaluation engineering and project ownership; no SOC-domain labeling obligation or analyst qualification is implied. The [current scope decision](docs/PROJECT_STATUS.md) supersedes earlier completion criteria while preserving every historical protocol and run artifact.

The original prompt-only condition lacked native output enforcement for either provider. After the repair, both models produced 16/16 valid structured outputs and matched 15/16 reference actions. GPT-6 Luna’s original 16/16 agreement on authored DEV cases is not evidence of model quality. A full frozen test, independent reference review and appropriately validated semantic evaluation would be needed for stronger quality or readiness claims; none is required to recognize the completed engineering work.

## Two preserved conditions

Both runs use the same 16 alerts, references, runbooks, embedding weights, model identifiers, application prompt v1, scorer, six-tool-call limit, five-generation limit, and 1,024-output-token limit. Run 2 changes the output protocol and disables an unrecorded OpenAI capability probe. It does not repair, extract or rescore the original answers.

| Condition | Run 1 | Run 2 |
| --- | --- | --- |
| Output support | Prompt-only request for bare JSON | Equivalent native JSON-schema support for both providers |
| Live responses | 16 per model, 32 total | 16 per model, 32 total |
| Source | `79e69aa536c8d33ebbe90f74ca5b0267ff04c8af` | `dc63b6897e4d286a8c7a318097e428ec999fa642` |
| Workflow | [43306449652](https://github.com/JordanG2D/soc-triage-evals/actions/runs/43306449652) | [43332755718](https://github.com/JordanG2D/soc-triage-evals/actions/runs/43332755718) |
| Evidence | [Original records and logs](evidence/vertical-slice-2026-11-12) | [Native-schema rerun records and logs](evidence/vertical-slice-2026-11-12-structured-rerun) |

All 11 files listed by the original SHA-256 manifest remain unchanged, as does the original manifest itself. All 32 original final strings match their native logs. The first report as originally published remains available in [Git history](https://github.com/JordanG2D/soc-triage-evals/blob/95eccb6cf1b60797f3d34cba36da2425637f3cf7/FINDINGS.md); its model-preference and total-cost interpretation are superseded by this investigation.

## Raw responses and diagnosis

Three complete, unchanged original Haiku responses are available as plain text: [A001](docs/raw-run1/A001.txt), [A006](docs/raw-run1/A006.txt), and [A015](docs/raw-run1/A015.txt). They are also printed in full in [the detailed investigation](docs/format-investigation-run1.md).

Seven Haiku responses began with `## Analysis` before a fenced JSON block. Nine began directly with a Markdown JSON fence. All 16 failed at the first character with `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. No response reached schema validation. All final generations stopped normally; none hit the token limit, and the largest final response used 682 of 1,024 available tokens.

This establishes a prompt-only serialization failure, not 16 separately established investigation errors. The parser behaved according to its declared contract. There is no evidence that the initial application prompt favored OpenAI: all 32 initial system strings were identical, and all 16 paired initial alert messages and tool definitions matched. Later histories differed because of tool choices and stopping behavior. OpenAI also used `reasoning_effort="none"`, while Haiku used its default non-thinking behavior. Inspect omits disabled final tool definitions for OpenAI and retains them with tool choice disabled for Anthropic; that API-specific context difference is retained and disclosed.

The harness was at fault for omitting available native output support and for treating that prompt-only result as a basis for model preference. Haiku’s original instruction-compliance failure remains an observation under the original condition. The records do not establish why the model chose those wrappers internally, and the content inside them has not been extracted for a replacement score.

## Harness repair and proof

Both providers now receive the same closed JSON schema, including the same required fields, severity/verdict enums, nullable technique ID, nested evidence structure and schema description. OpenAI uses strict Responses `text.format`; Anthropic uses current Messages `output_config.format`. The pinned Inspect version requires a provider-level request-body route for Anthropic because its generation-level extra body silently filters that field and its older schema converter rewrites scalar nodes.

The shared schema inlines references and removes unsupported constraints symmetrically. The original strict local `Decision` validator remains unchanged and still checks lengths, array limits, technique pattern and all other local constraints. No fence stripping, answer repair, fallback model, relaxed scoring or quality retry was introduced.

Real-SDK offline HTTP tests verify the transmitted schema dictionaries and their hash, exact system text, both ordinary and tool-disabled generation turns, nested evidence fields, and one HTTP request per reservation. The schema hash is `914ffe87ef10c4afcc0b0ee00d48c5a91ce26b837e5fd00d532a6f24be26a330`; the unchanged system-prompt hash is `500abc9bc7b001bca7a7bd3a7ebfa30fbcf9f86d466b71df1e47f03c0162d268`. Every R2 generation records that output contract. All 16 paired initial text projections also match R1.

See [the protocol declared before R2](docs/STRUCTURED_OUTPUT.md) and [sanitized HTTP proof captures](docs/provider-wire-proof). The proof files are explicitly **OFFLINE_MOCK** captures of the pinned SDKs, not historical live HTTP captures. Native support follows the [OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs) and [Anthropic](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) documented APIs. The repair source passed all 163 offline tests and the fixed 16-case regression before R2. The final source passes 181 checks, including the added reconciliation-hold checks before any future paid allocation. The same free suite runs in CI before any live allocation.

## Results without retrospective rescoring

Each cell uses all 16 cases for that model/condition. Invalid outputs remain failures in all-case accuracy. Haiku’s Run 1 zeros therefore describe the strict contract score, not an independently measured reasoning-error rate.

| Measure | R1 GPT-6 Luna | R1 Haiku 4.5 | R2 GPT-6 Luna | R2 Haiku 4.5 |
| --- | ---: | ---: | ---: | ---: |
| Valid structured outputs | 16/16 | 0/16 | 16/16 | 16/16 |
| Reference triage-action matches | 16/16 | 0/16 | 15/16 | 15/16 |
| Exact reference severity | 16/16 | 0/16 | 15/16 | 9/16 |
| Exactly off-by-one severity | 0/16 | 0/16 invalid | 1/16 | 7/16 |
| Within-one severity | 16/16 | 0/16 | 16/16 | 16/16 |
| Severity MAE, valid denominator | 0.0, n=16 | unavailable, n=0 | 0.0625, n=16 | 0.4375, n=16 |
| Acceptable technique ID | 13/16 | 0/16 | 14/16 | 12/16 |
| Required tool alternatives covered | 19/19 | 19/19 | 19/19 | 19/19 |
| Total tool calls | 62 | 56 | 64 | 53 |
| Forbidden/extra tool calls | 9 | 8 | 12 | 4 |
| Cases with forbidden calls | 6 | 6 | 7 | 4 |
| Tool execution errors / cap breaches | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Valid cited source IDs | 70/70 | unavailable | 66/66 | 108/108 |
| Mean illustrative event-truth cost | 0.125 | 10.0 | 0.0 | 0.0 |
| Mean end-to-end latency | 9.28 s | 8.56 s | 8.73 s | 6.81 s |
| P95 end-to-end latency | 11.37 s | 9.63 s | 10.10 s | 9.33 s |
| Recorded triage token-price estimate | $0.010680765* | $0.177111 | $0.010030065 | $0.184206 |

*The R1 OpenAI amount excludes unresolved capability-probe usage, as explained below. None of these estimates is a retrieved invoice. Latency covers all provider generations, local tools and parsing for one alert; R1 OpenAI latency can also include the probe path. P95 uses linear interpolation. Latency and cost changes cannot be attributed solely to the output schema: tool trajectories, removed probe overhead, provider formatting effects and ordinary sampling/network variation also changed.

### Action confusion matrices

Run 1 GPT-6 Luna placed all seven `true_positive`, six `benign` and three `needs_escalation` references on their diagonal. Run 1 Haiku placed the same 7/6/3 reference groups in `invalid`. The original report files retain those matrices.

Both R2 models produced the same following matrix:

| Reference action | true_positive | benign | needs_escalation | invalid |
| --- | ---: | ---: | ---: | ---: |
| true_positive | 7 | 0 | 0 | 0 |
| benign | 0 | 6 | 0 | 0 |
| needs_escalation | 1 | 0 | 2 | 0 |

### Remaining observed failures

**Policy retrieval:** both R2 models returned `true_positive` for A012, while the reference requires `needs_escalation` for unauthorized data export from a critical asset. Both assigned severity 1. Neither actually received the required policy runbook RB18: OpenAI retrieved RB02/RB04/RB13 and Haiku retrieved RB12/RB13. The host context names a critical-asset review policy as a retrieval breadcrumb but does not state its escalation rule. In R1, only GPT-6 Luna on A012 actually received RB18 and matched the policy action; no R1 Haiku response or any R2 response received RB18. The models issued different searches across trajectories. This is an end-to-end policy-retrieval failure, not evidence that either model ignored a policy it saw. It also shows why 19/19 required tool alternatives does not establish successful retrieval of required evidence. Retrieval recall and policy clarity need review before the full protocol is frozen; no such tuning was performed during this repair.

**Severity:** GPT-6 Luna assigned A013 severity 3 rather than reference 2. Haiku’s seven mismatches were all one level more urgent than the reference: A002/A004/A005/A007/A013/A014 received 1 rather than 2; A010 received 2 rather than 3. These are descriptive reference-label differences on DEV, not independently validated operational error rates.

**Technique selection:** GPT-6 Luna used T1219 instead of T1059.001 on A004 and historical T1562.001 instead of current T1685 on A005. Haiku also used T1562.001 on A005, T1078.004 rather than the accepted T1078 on A007, T1020 rather than T1041 on A012, and T1110.003 rather than `null` on A015. Technique scoring uses the unchanged declared acceptable sets; no taxonomy-based partial credit was added after observing results.

**Tool waste:** GPT-6 Luna used 12 forbidden calls in seven cases, including all four tools on the self-contained no-tool A011 case. Haiku used four forbidden calls in four cases. Both covered every required alternative and had no execution errors or tool-cap violations. Repeated tool names can refer to different IP arguments and are not automatically identical duplicate requests.

**Metric limitation:** zero R2 event-truth cost does not mean zero action errors. The illustrative matrix assigns malicious→`true_positive` zero, but the required A012 escalation costs two. Thus it does not penalize this policy-action mismatch and cannot be used alone as an overall quality or shipping measure. The action score remains 15/16. The matrix is preserved rather than changed retrospectively; its intended scope needs review before the full evaluation is frozen.

Citation IDs establish only that a source was actually exposed. They do not establish that a claim follows from it. No semantic faithfulness grades or human labels have been assigned.

## Paired uncertainty and interpretation

The existing paired percentile bootstrap resamples whole families, retaining paired alerts and within-family variants: eight families, 16 pairs, 2,000 resamples, seed 1729, 95% intervals. Differences below are Haiku minus GPT-6 Luna.

| Paired measure | R1 difference and interval | R2 difference and interval |
| --- | --- | --- |
| Reference-action accuracy | -1.000, [-1.000, -1.000] | 0.000, [0.000, 0.000] |
| Mean event-truth cost | +9.875, [9.625, 10.000] | 0.000, [0.000, 0.000] |

R1’s large difference was dominated by the prompt-only formatting contract. R2’s degenerate intervals arise because every pair has the same assigned action/cost scores. They establish neither general model equivalence nor a quality ranking. Severity and technique counts above are descriptive; no new significance claim is made. These are authored DEV families, not the future full test split. Each condition has one trajectory per alert, with no controlled replication to separate schema effects from response variability.

## Request accounting and historical cost correction

The pinned OpenAI adapter can make an automatic greeting generation to detect reasoning-summary support when that setting is unset. Its probe omits an explicit output cap, and its usage is absent from the returned triage-generation usage. A reproduction of the old configuration produced three SDK POSTs for two requested generations/reservations; the extra call was the probe. A successful or deterministic rejection is cached within a provider instance, while a transient error can allow another attempt. The original agent created a fresh provider instance per alert.

This proves the old code path, not the exact number or cost of historical live probes. Original live HTTP logs and an account invoice were not retained. **The earlier $0.187791765 figure covers recorded triage generations only and must not be called the complete bill.** The recorded R1 request-accounting ceiling of $0.972598 likewise excludes unresolved probe usage. Original budget evidence remains unchanged.

R2 explicitly disables that probe path with `reasoning_summary="none"`. Its offline SDK tests show one HTTP request per reserved generation for both providers. The retained R2 SQLite ledger passes integrity checks and contains **149 settled reservations** (80 OpenAI, 69 Anthropic), matching all recorded usage and the 32 per-case charges. There are no pending, uncertain or bound-violation rows. The conservative charged ceiling is **$1.085740**; the standard-price recorded token estimate is **$0.194236065**. Both remain distinct from provider billing.

The durable allocation journal now counts **$10 of the lifetime $20 limit**: one nonrefundable $5 allocation per run, with unused allocation not automatically reclaimed. There is no claim that allocated dollars equal the provider bill, and historical unrecorded probe usage remains a reconciliation limit. No further paid run has been started. The current journal sets `requires_usage_reconciliation: true`; the current allocator blocks another paid allocation until historical usage is reconciled. No allocation was refunded or reset. Original R1 hidden SQLite state was omitted by the first artifact uploader; R2 retains the [actual SQLite file](evidence/vertical-slice-2026-11-12-structured-rerun/request-budget.sqlite3), a [readable export](evidence/vertical-slice-2026-11-12-structured-rerun/request-ledger.json), and the lease as well as the budget summary.

## Engineering completion and optional semantic calibration

The engineering deliverable demonstrates real model execution, deterministic scoring, automated regression checks, evidence preservation, spending controls, failure investigation and a corrected rerun with equivalent provider output support. That milestone is complete. The project owner is not assigned the role of an independent SOC analyst or a mandatory labeling task.

The [20-response candidate pack](evidence/vertical-slice-2026-11-12-structured-rerun/human-calibration.json) and [offline review form](evidence/vertical-slice-2026-11-12-structured-rerun/label-20-responses.html) remain unchanged and entirely unlabeled. The original run’s pack is also preserved. Historical artifacts retain their original status strings and instructions as records of the earlier plan; they do not impose the current completion criteria.

**Semantic faithfulness calibration: pending, not performed; judge uncalibrated.** This is neither a failed evaluation nor a completed validation. The existing calibration checks remain safeguards against claiming human agreement without genuine review; they are not a gate on portfolio completion. No AI-generated labels have been substituted or described as human ground truth.

If separately authorized, future semantic research could use an independent domain expert with a documented rubric, qualifications, label provenance and disagreement handling, or a clearly identified LLM-as-judge protocol with its model, prompts, sampling and limitations reported. Expert judgments are not automatically infallible ground truth, and automated judge scores are not human validation. Neither option is assigned, initiated or silently treated as validated truth.

The reference labels remain synthetic authoring assumptions, not independently validated SOC judgments. The small DEV sample, retrieval miss, illustrative cost-metric limitation and unresolved historical probe billing remain documented limitations. There is no model-quality ranking, operational SOC-readiness claim or shipping recommendation.

The [current scope decision](docs/PROJECT_STATUS.md) records the revised acceptance criteria. Additional paid runs, dataset expansion, scoring-method changes, prompt v2, the held-out split and the frozen comparison require separate authorization. The existing billing-reconciliation hold remains in place. No implementation or scoring change is part of this documentation update.

## Reproduction records

- [R1 manifest](evidence/vertical-slice-2026-11-12/manifest.json), [original responses](evidence/vertical-slice-2026-11-12/records.jsonl), and [original per-model reports](evidence/vertical-slice-2026-11-12).
- [R2 manifest](evidence/vertical-slice-2026-11-12-structured-rerun/manifest.json), [new responses](evidence/vertical-slice-2026-11-12-structured-rerun/records.jsonl), [OpenAI report](evidence/vertical-slice-2026-11-12-structured-rerun/openai/report.json), [Haiku report](evidence/vertical-slice-2026-11-12-structured-rerun/anthropic/report.json), and [paired statistics](evidence/vertical-slice-2026-11-12-structured-rerun/paired-dev-comparison.json).
- Both use returned model identities `gpt-6-luna` and `claude-haiku-4-5-20251001`. The former is an alias, limiting exact weight reproducibility.
- Python 3.12, Inspect AI 0.3.287; unchanged dependencies in `uv.lock`, embedding checksums in `config/embedding.json`, [runtime notes](docs/DEPENDENCIES.md), and offline reproduction command `bash scripts/evaluate.sh`.
