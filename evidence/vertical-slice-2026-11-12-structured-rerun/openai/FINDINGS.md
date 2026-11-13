# Live synthetic development evaluation

These numbers describe actual model responses on a small synthetic development slice. Billing and timing evidence must come from the live run metadata. They do not establish operational SOC performance.

All 16 alerts belong to DEV. No full dataset or frozen comparison has been run.

| Measure | Observed value |
| --- | --- |
| Scored cases | 16 |
| Expected triage-action accuracy | 0.938 |
| Mean illustrative error cost | 0.000 |
| Always-escalate mean error cost | 1.375 |
| Always-escalate action accuracy | 0.188 |
| False-benign decisions on malicious events | 0 / 8 |
| Invalid outputs | 0 |
| Exact / within-one severity accuracy | 0.938 / 1.000 |
| Exactly off-by-one severity rate | 0.062 |
| Severity MAE (valid denominator) | 0.0625 (16) |
| Acceptable ATT&CK technique accuracy | 0.875 |
| Mean required-tool alternative coverage | 1.000 |
| Extra / forbidden tool calls | 12 / 12 |
| Citation ID validity | 1.000 |

Expected triage action and event truth are separate: an unknown event may correctly require escalation. The predeclared event-truth cost matrix is preserved in report.json; a benign decision on a malicious event has the largest valid-action cost (10). Invalid actions also cost 10.

Citation IDs only establish that a source was actually exposed. A valid ID does not prove that its cited claim follows from that source. Fact-text recall and source coverage are likewise mechanical.

Regression status: not_run.

Faithfulness judge: **UNCALIBRATED — pending 20 human labels**. No human labels, judge labels, or agreement are fabricated. Export 20 actual live responses with blank labels, then obtain the human review before running the judge.

Paired uncertainty is computed only for actual matched configurations by resampling whole alert families. Missing pairs or unscored values are errors; a single configuration has no paired interval.

Limits: this development harness supports inspection and regression work. It does not establish a ship decision, operational SOC readiness, or frozen-test performance.

Exploratory actual paired DEV comparison (candidate minus baseline):
Baseline: `openai/gpt-6-luna`; candidate: `anthropic/claude-haiku-4-5-20251001`.

- error_cost: mean difference 0.0000, 95% family-bootstrap interval [0.0000, 0.0000], 16 matched alerts in 8 families.
- verdict_correct: mean difference 0.0000, 95% family-bootstrap interval [0.0000, 0.0000], 16 matched alerts in 8 families.

Lower error cost and higher action accuracy are preferable. These intervals use 32 actual responses on the same 16 DEV alerts. They are exploratory with few synthetic families and do not constitute the frozen comparison.
