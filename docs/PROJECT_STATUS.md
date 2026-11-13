# Project status and accepted scope

**Current scope and acceptance clarification — November 12, 2026 (America/Chicago), at the project owner's direction.**

The public AI engineering portfolio deliverable is complete for the authorized 16-alert development slice. It includes the working agent and evaluation pipeline, the original live run, the output-format investigation, the equivalent native-schema repair, and the same-slice rerun. Semantic faithfulness calibration has not been performed; the judge is uncalibrated, not failed. Human labeling is optional future evaluation and is not a condition of portfolio completion.

This current clarification supersedes earlier planning language that made 20 labels from the human owner a completion gate. It does not rewrite the original protocol, run records, or acceptance history. Those records retain their original meaning and remain preserved.

## Completed engineering capabilities

- An original synthetic dataset of 16 alerts in eight behavior families, with evaluator-only scenario references, four deterministic read-only tools, and 30 original runbooks searched through pinned local embeddings.
- A bounded native Inspect agent, an offline recorded-fixture path, meaningful tests, deterministic scorers, fixed regression checks, and reproducible reports with source, usage, and observed-tool evidence.
- Investigation of the first run's Markdown-wrapped Haiku answers and equivalent native JSON-schema support for both providers. The rerun produced 16/16 valid outputs and 15/16 reference-action matches for each model. Original responses remain unchanged; neither run's answers were repaired or retrospectively rescored.
- Preserved raw responses, native logs, SDK request-body proofs clearly marked as offline reproductions, paired development statistics, and request-accounting evidence. Blank 20-response packs and an offline review form are available for optional future calibration.

See [the findings](../FINDINGS.md), [dataset documentation](../DATASET.md), and the two retained evidence sets: [original run](../evidence/vertical-slice-2026-11-12) and [native-schema rerun](../evidence/vertical-slice-2026-11-12-structured-rerun).

## Remaining limits on claims

All 16 cases are authored development material with synthetic reference judgments. The full family-held-out test, independent reference validation, and semantic faithfulness calibration have not been performed. Neither development run establishes a general model-quality ranking, operational SOC readiness, or a shipping recommendation.

Known limits remain visible in the findings: both rerun models missed the critical-asset escalation disposition after the required policy was not retrieved; severity, technique, and tool-policy mismatches remain; and zero event-truth cost does not mean zero policy-action error. Mechanical citation validity does not establish that a cited source supports a claim. Completing the engineering portfolio does not turn these observations into passes or erase them.

Historical OpenAI capability-probe usage from the first run remains unreconciled. The recorded triage token estimate is not the complete provider bill. The existing hold on further paid allocations remains in effect; see [the spending contract](BUDGET.md).

## Optional future evaluation

Expert review or exploratory LLM judging may be proposed as separate future work. Neither is required to close this portfolio scope. Assessments remain evaluation evidence with provenance and limits; they do not by themselves establish operational ground truth. Model-generated assessments must be identified as AI assessments; they are not human labels or independent ground truth. No semantic faithfulness or human-agreement result is claimed here.

If human calibration is later pursued, it must use genuine reviewer annotations in a new derived artifact with clear provenance. Existing blank packs remain unchanged. The judge's current guards remain correct for qualifying a human-calibration claim; they do not define engineering-portfolio completion. This status change enables no judge calls and assigns no labels.

## Controls and history remain unchanged

Additional paid runs, dataset expansion, a frozen comparison, or changes to evaluation and scoring methods require a separately authorized scope. The spending journal, reconciliation hold, request reservations, model and tool limits, and preservation of failed outputs remain in force. No new run or method change is authorized by this document.

The original [structured-output protocol](STRUCTURED_OUTPUT.md), raw answers, reports, manifests, and unlabeled calibration materials remain historical evidence. This clarification changes current project status and completion criteria only. It changes no implementation, data, scoring, result, or evidence byte.
