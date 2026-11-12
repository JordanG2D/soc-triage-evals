# SOC triage evaluations

A small security-alert triage agent and an Inspect AI evaluation suite, built from original synthetic material as a public AI engineering portfolio project. Python 3.12, MIT license.

**Current scope:** a 16-alert development vertical slice with four deterministic tools, 30 original runbooks, local semantic retrieval, structured decisions, scoring, reports, and regression checks. A live development run is pending. The faithfulness judge remains uncalibrated until the human owner labels 20 actual responses. Full dataset expansion and the frozen comparison have not started.

```mermaid
flowchart LR
  A[Synthetic alert JSON] --> B[Bounded Inspect tool loop]
  B --> C[IP, user and host fixtures]
  B --> D[Local runbook vector index]
  E[Pinned local Model2Vec weights] --> D
  B --> F[Structured decision and observed evidence]
  F --> G[Deterministic scoring and reports]
  H[Evaluator-only reference labels] --> G
  F --> I[20 blinded responses for human labeling]
  J[Durable allocation journal and request reservations] --> B
```

Run the complete offline evaluation with one command, after installing [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
bash scripts/evaluate.sh
```

The first setup downloads checksum-pinned, MIT-licensed [Model2Vec weights](https://huggingface.co/minishlab/potion-base-2M) from a fixed revision. Evaluation then uses local files with network access disabled for the embedding library. No provider key is needed for the offline suite. Outputs are in `artifacts/offline/` and native Inspect JSON logs in `artifacts/recorded/inspect/`. Tested compatibility pins and the JSON log-format choice are documented in [runtime compatibility](docs/DEPENDENCIES.md).

Offline fixtures exercise all four real tool implementations and the scoring pipeline. Their perfect target-label matches are prewritten expectations and carry **no claim about model performance**. See [FINDINGS.md](FINDINGS.md), [DATASET.md](DATASET.md), and the committed [fixture baseline](baselines/offline.json).

The model receives alert fields and tool results. Ground-truth labels, tool policies, and required-summary facts are stored separately and read only by the evaluator. IP, user, and host lookups are fake and deterministic. `runbook_search` embeds the query locally and searches an in-memory cosine vector index. Runbooks are generic guidance rather than alert answer keys. The loop allows at most six tool calls, five generations, and 1,024 output tokens per generation.

Scoring covers expected triage action and its confusion matrix; an event-truth error-cost policy that penalizes false-benign malicious events most; severity accuracy, within-one rate and MAE; acceptable ATT&CK IDs; tool necessity and waste; mechanical citation validity; and live token-cost estimates and end-to-end latency. Semantic faithfulness has a written rubric and a human calibration gate. Citation validity does not establish faithfulness.

Live runs are manual GitHub Actions only. Add repository secrets `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, then select **Actions → Bounded live development slice → Run workflow** on `main`. The fixed development configurations are prompt `v1` with `openai/gpt-6-luna` and `anthropic/claude-haiku-4-5-20251001`. The former is an alias; returned model identity is retained. This run is exploratory development evidence, not the later two-prompt frozen comparison.

Before requesting either model, the workflow commits a nonrefundable $5 allocation to [.budget/allocations.json](.budget/allocations.json). Allocations cannot exceed $20 total; failed or interrupted runs retain their allocation. Each request also reserves a conservative maximum in SQLite before dispatch; uncertain requests retain that reservation. Automatic model retries are disabled. Conservative accounting exceeds declared standard-service token rates; reported token costs remain estimates until billing is reconciled. These controls apply to this project's workflow and do not cap unrelated account use. See [budget design](docs/BUDGET.md).

Pull requests and pushes run the entire 16-case offline fixture suite, native Inspect task, and fixed metric regression baseline with no paid requests. An exact mismatch fails the deterministic baseline check. The paid workflow has no automatic trigger. Source dependencies, embedding revision, source hashes, observed tools, model usage, and run identity are retained for review.

## How this was built

Joshua Jordan directed the scope, public release, spending cap, and human calibration boundary. OpenAI Codex coding agents implemented this original repository: the coordinating agent, `soc_clean_agent` (agent/tools/retrieval/Inspect), `soc_clean_data` (synthetic data/runbooks and budget review), and `soc_clean_evals` (metrics/statistics/reports/calibration). The AI agents wrote development reference labels and test fixtures. They do not supply the 20 human faithfulness labels. No private source, private history, customer records, or employer data were imported.
