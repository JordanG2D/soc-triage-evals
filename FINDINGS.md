# Live development vertical slice

> Investigation update before the repair run: the first run used prompt-only JSON instructions for both providers. Haiku's 16 parse failures do not establish 16 investigation errors. GPT-6 Luna's 16/16 agreement on 16 authored DEV cases is not evidence of quality; the full frozen test and faithfulness calibration are still needed. The $0.187791765 estimate below covers recorded triage generations and excludes unresolved automatic OpenAI probe usage. Original evidence is preserved. See [the raw-response audit](docs/format-investigation-run1.md) and [the declared repair protocol](docs/STRUCTURED_OUTPUT.md). A same-slice native-schema rerun is authorized; no dataset expansion is underway.

The first live slice completed on 2026-11-12: **16 synthetic development alerts × two models × prompt v1 = 32 actual responses**, with native Inspect JSON logs and no automatic retries. [The live workflow succeeded](https://github.com/JordanG2D/soc-triage-evals/actions/runs/43306449652); the free regression workflow also passed all 130 tests and the native 16-case recorded task.

GPT-6 Luna satisfied the strict JSON contract on all 16 cases and matched all expected triage actions and severities. Haiku returned Markdown-wrapped answers on all 16 cases and therefore failed the exact-one-JSON-object contract. Its zero action/severity/technique scores include those parsing failures; the parser never reached schema validation. No answer was repaired, extracted, retried for quality, or rescored.

All alerts are DEV, grouped into eight authored behavior families. There is no held-out test split, second prompt, full dataset, frozen comparison, human faithfulness result, or ship recommendation.

## Results

| Measure | GPT-6 Luna | Claude Haiku 4.5 |
| --- | ---: | ---: |
| Actual responses | 16 | 16 |
| Valid structured outputs | 16/16 | 0/16 |
| Expected triage-action accuracy | 16/16 (100%) | 0/16 (0%) |
| Exact severity accuracy | 16/16 (100%) | 0/16 (0%) |
| Exactly off-by-one severity rate | 0/16 | 0/16 |
| Within-one severity accuracy | 16/16 | 0/16 |
| Severity MAE, valid denominator | 0.0, n=16 | unavailable, n=0 |
| Acceptable ATT&CK technique accuracy | 13/16 (81.25%) | 0/16 (0%) |
| Required tool alternatives covered | 19/19 | 19/19 |
| Total tool calls | 62 | 56 |
| Extra calls, all forbidden under per-case policy | 9 | 8 |
| Cases with forbidden tool use | 6 | 6 |
| Tool execution errors / exceeded call cap | 0 / 0 | 0 / 0 |
| Valid cited source IDs | 70/70 | unavailable, no parseable citations |
| Mean illustrative event-truth error cost | 0.125 | 10.0 |
| Always-escalate error-cost baseline | 1.375 | 1.375 |
| False-benign decisions on malicious events | 0/8 | 0/8, with 8 invalid malicious-case outputs |
| Standard-price token cost estimate | $0.010681 | $0.177111 |
| Estimated mean cost per alert | $0.000668 | $0.011069 |
| Mean end-to-end response latency | 9.28 s | 8.56 s |
| P95 end-to-end response latency | 11.37 s | 9.63 s |

Latency includes all generations, local tools, and parsing per alert. P95 uses linear interpolation across the 16 observed response times. Token prices are estimates from reported usage, not retrieved invoices. Total estimated cost is **$0.187791765**. The conservative request ledger charged **$0.972598**, with 150 settled generations and no pending, uncertain, or overrun reservations. The whole **$5 allocation remains counted against the lifetime $20 limit**; unused allocation is not automatically reclaimed.

An off-by-one rate of zero for Haiku reflects invalid outputs, not valid severity estimates. Its zero false-benign count likewise reflects a lack of valid decisions. Missing and invalid cases stay in all-case accuracy denominators. Valid severity MAE and citation validity report their separate denominators.

### Triage-action confusion matrices

Rows are reference triage actions; columns are predicted actions. Event truth is separately retained as malicious, benign, or unknown.

| GPT-6 Luna reference | true_positive | benign | needs_escalation | invalid |
| --- | ---: | ---: | ---: | ---: |
| true_positive | 7 | 0 | 0 | 0 |
| benign | 0 | 6 | 0 | 0 |
| needs_escalation | 0 | 0 | 3 | 0 |

| Haiku reference | true_positive | benign | needs_escalation | invalid |
| --- | ---: | ---: | ---: | ---: |
| true_positive | 0 | 0 | 0 | 7 |
| benign | 0 | 0 | 0 | 6 |
| needs_escalation | 0 | 0 | 0 | 3 |

The predeclared cost table penalizes a benign decision on a malicious event at 10 and assigns invalid actions a cost of 10. The malicious critical-export case correctly requires escalation under lab policy, which carries a cost of 2 in the illustrative event-truth table even when the expected triage action is matched. Costs are declared policy weights, not measured business losses.

## Failure modes and examples

**Output-contract failure:** all 16 Haiku answers failed JSON decoding at the first character. Seven began with `## Analysis` and later included a fenced JSON block; nine began directly with a Markdown JSON fence. For example, A001 begins with an analysis section rather than the required JSON object. These are contract failures; this run does not establish separate reasoning-error rates for the embedded fields. All 16 final generations stopped normally; no length-limit stop was observed, and the largest final response used 682 of 1,024 available output tokens. Original responses remain unchanged.

**Technique over-attribution or taxonomy mismatch:** three GPT-6 Luna technique IDs fall outside the declared acceptable set. For A006, an approved maintenance task is correctly classified as benign with severity 4, but the model assigns `T1053.005` while the reference permits `null`. The other two mismatches were `T1219` in place of PowerShell `T1059.001`, and the historical `T1562.001` in place of the current `T1685` target. This exposes both technique selection and taxonomy-version sensitivity under the lab's labeling rule.

**Unnecessary investigation:** both models covered all required tool alternatives but used forbidden tools in six cases. GPT-6 Luna made nine such calls; Haiku made eight. A006's GPT-6 Luna trace includes an unnecessary `ip_reputation` lookup. The self-contained benign scenario exercises whether a model can stop without looking up more context. Repeated tool names can involve different arguments; the reported name-repeat count is not proof of duplicate identical requests.

**Mechanical evidence checks:** GPT-6 Luna's 70 citation IDs were all actually exposed, but source-ID validity does not establish support for the associated claims. Exact reference-fact string overlap is zero despite valid decisions, illustrating why lexical matching is reported only as a mechanical diagnostic. No semantic faithfulness grades have been assigned.

## Exploratory paired uncertainty

The predeclared paired percentile bootstrap resamples whole families, preserving each alert's model pair and within-family variants: eight families, 16 pairs, 2,000 resamples, seed 1729, 95% intervals. Differences below are **Haiku minus GPT-6 Luna**.

| Paired measure | Observed difference | 95% family-bootstrap interval |
| --- | ---: | --- |
| Expected-action accuracy | -1.000 | [-1.000, -1.000] |
| Mean illustrative error cost | +9.875 | [9.625, 10.000] |

The intervals exclude zero for these contract-based scores on this sample. The degenerate accuracy interval occurs because every observed pair has the same difference. These intervals resample the eight authored DEV families; they do not establish general model dominance, future precision, operational security performance, or human-judged faithfulness. Only one generation trajectory per alert/configuration was observed.

## Human calibration handoff

The [20-response blank pack](evidence/vertical-slice-2026-11-12/human-calibration.json) contains the ten cases declared before the run for each model, followed by a seeded blind shuffle. It omits model/configuration identities where feasible and includes only the alert, actual observed tools, and final response. Indirect clues can remain in outputs. The downloadable [offline review form](evidence/vertical-slice-2026-11-12/label-20-responses.html) starts with no choices selected and downloads the human's completed JSON after all 20 choices, reasons, and a reviewer name are entered. No AI labels or suggested grades are supplied.

The faithfulness judge is **UNCALIBRATED — pending 20 human labels**. Judge generation refuses incomplete human review, and agreement remains unset. This handoff does not ask the reviewer to relabel operational correctness or repair JSON; the written rubric assesses support for material factual claims in the actual displayed evidence.

## Recommendation and checkpoint

Use GPT-6 Luna as the next development baseline. The next proposed engineering iteration should enforce or improve Haiku's output contract and reduce unnecessary tools, with any new prompt/version declared before another run. These are recommendations for review, not changes made after seeing results. **Neither configuration is ready for a shipping recommendation.** Synthetic references have not received independent domain validation, and faithfulness calibration is pending.

The authorized vertical slice stops here. Dataset expansion, a 70/30 family-held-out split, prompt v2, the frozen two-prompt comparison, judge calls, and further paid runs have not started.

## Reproduction and evidence

- Live source: [`79e69aa536c8d33ebbe90f74ca5b0267ff04c8af`](https://github.com/JordanG2D/soc-triage-evals/tree/79e69aa536c8d33ebbe90f74ca5b0267ff04c8af).
- [Workflow run](https://github.com/JordanG2D/soc-triage-evals/actions/runs/43306449652), run/attempt `43306449652:1`; [durable allocation commit](https://github.com/JordanG2D/soc-triage-evals/commit/226e9ba6a60349fb5ad5de35e5da069cc1f11df6).
- Returned model identities: `gpt-6-luna` and `claude-haiku-4-5-20251001`. The OpenAI name is an alias, so exact provider-weight reproducibility is limited.
- [32 original response records](evidence/vertical-slice-2026-11-12/records.jsonl), [OpenAI report](evidence/vertical-slice-2026-11-12/openai/report.json), [Anthropic report](evidence/vertical-slice-2026-11-12/anthropic/report.json), [paired statistics](evidence/vertical-slice-2026-11-12/paired-dev-comparison.json), and [budget summary](evidence/vertical-slice-2026-11-12/budget.json).
- Native Inspect JSON logs are retained under [the evidence directory](evidence/vertical-slice-2026-11-12/inspect), with a [SHA-256 manifest](evidence/vertical-slice-2026-11-12/manifest.json). Source/input hashes and actually exposed evidence are retained in original records.
- Python 3.12, Inspect AI 0.3.287; complete dependencies in `uv.lock`, embedding revision/checksums in `config/embedding.json`, and compatibility notes in [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).

The original artifact uploader omitted the hidden SQLite state directory. The durable repository allocation, budget summary, and all 150 usage events are retained; their conservative charges reconstruct the $0.972598 total. The workflow now explicitly retains hidden state in future manual runs.

Later changes to the review-form presentation, the reporting display of exactly-off-by-one severity, or hidden-file artifact retention do not change the frozen agent, prompts, cases, scores, or original live evidence from this run. Reproduce the offline fixture checks with `bash scripts/evaluate.sh`; they validate pipeline mechanics and are not model-quality results.
