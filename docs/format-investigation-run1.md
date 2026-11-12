# Run 1 output-format investigation

This audit explains the original Haiku format failures without repairing answers, extracting fenced JSON for scoring, changing scores, or assigning semantic faithfulness or human labels. It makes no product change and does not replace the main findings. The original 32 response records, native logs, reports, calibration material, and manifest remain unchanged.

## Original evidence and scope

- Workflow run/attempt: `43306449652:1`, [original run](https://github.com/JordanG2D/soc-triage-evals/actions/runs/43306449652).
- Agent/data source: `79e69aa536c8d33ebbe90f74ca5b0267ff04c8af`.
- Conditions: `openai/gpt-6-luna` and `anthropic/claude-haiku-4-5-20251001`, one trajectory for each of the same 16 synthetic DEV alerts under prompt v1.
- Runtime: Python 3.12 and Inspect AI `0.3.287` as recorded in the native evaluation metadata. No held-out or frozen test is involved.
- [Original SHA-256 manifest](../evidence/vertical-slice-2026-11-12/manifest.json) and [32 response records](../evidence/vertical-slice-2026-11-12/records.jsonl).
- [openai native Inspect JSON](../evidence/vertical-slice-2026-11-12/inspect/openai/2026-11-12T21-04-03-00-00_task_fDYzbPau6YAzyfVxBnrLJE.json), SHA-256 `46dc44de353e712ac26c06f793263a04c2ac377f62adfa1cdc5063cbc1df0678`.
- [anthropic native Inspect JSON](../evidence/vertical-slice-2026-11-12/inspect/anthropic/2026-11-12T21-06-34-00-00_task_PLkYHSqbsbotbyXsYB3SFL.json), SHA-256 `18b870cf15c1ca0bac45f308f73d415cd3ea0c350547ed71fcd0471fa1b7859e`.

Every manifest-listed file matched its existing digest during this audit. The final completion text agrees exactly between each native sample's `output.completion`, its `metadata.triage_result.raw_output`, and the corresponding original response record: all 32 comparisons matched. No cleanup or replacement of original evidence is part of this investigation.

## Recorded failure, before any interpretation

| Observation | OpenAI | Anthropic |
| --- | ---: | ---: |
| Original responses | 16 | 16 |
| Bare JSON at the start of the final response | 16 | 0 |
| Markdown analysis followed by a JSON fence | 0 | 7 |
| Starts directly with a Markdown JSON fence | 0 | 9 |
| Recorded parse errors | 0 | 16 |
| Final provider stop reason `stop` | 16 | 16 |
| Length-limit stops across all generation events | 0 | 0 |
| Generation events / executed tool calls | 78 / 62 | 72 / 56 |
| Final output-token range | 165–337 | 341–682 |

All 16 Haiku samples have exactly the same stored error:

```text
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

The parser accepts the complete final string as exactly one JSON value, then applies the strict decision schema. An initial `#` or backtick is not a JSON value, so these responses fail at the first character. Their normal stop reasons, complete closing Markdown fences, and token use below the shared 1,024-token cap do not support a truncation explanation.

Schema validation was never reached for these 16 answers. The observed error is therefore not evidence of missing keys, a wrong `summary` type, or 16 independently wrong decisions. The expected contract has only `verdict`, integer `severity`, `technique_id` string-or-null, string `summary`, and `evidence` items with `source_id`/`fact`; no additional keys are allowed. JSON-looking text inside the quoted answers is not accepted, repaired, or rescored in this audit. No hidden success rate is inferred from those fragments.

The seven analysis-prefixed sample IDs are A001, A003, A006, A007, A008, A011, and A016. The nine directly fenced IDs are A002, A004, A005, A009, A010, A012, A013, A014, and A015.

## Prompt parity and generation controls in the native logs

### Initial instructions and available tools

All 32 native system messages are byte-identical: 1,485 UTF-8 bytes, SHA-256 `500abc9bc7b001bca7a7bd3a7ebfa30fbcf9f86d466b71df1e47f03c0162d268`. Each explicitly requires exactly one JSON object and no Markdown. For every alert, the two initial user packets are also byte-identical: 16 of 16 paired inputs match. Each initial user message equals that native sample's `input`, and every sample's `target` is empty.

The four initial Inspect tool definitions also match across conditions: `ip_reputation`, `user_context`, `host_context`, and `runbook_search`. Canonical JSON SHA-256 of that definition list is `b3e538cdd7d6b2832694d45b5341d8c0a5c4736827c1e1ccfaeedb73fec26e19`. This establishes parity of the recorded initial instructions and tool interfaces; it does not establish that the complete provider wire requests or later conversations were identical.

### Shared and different recorded settings

Every model event records `max_tokens: 1024`, `max_retries: 0`, and `parallel_tool_calls: false`. OpenAI's 78 events additionally record `reasoning_effort: "none"`; Anthropic's 72 events do not record a reasoning-effort setting. Neither event configuration contains a response-schema or output-format field. The declared system instructions allow six tool calls and five generation turns; the observed trajectories use at most four calls and five generations per alert.

The outer native evaluation records `model: "mockllm/model"` because the Inspect task uses a wrapper model while its custom solver dispatches the actual provider calls. Actual condition identities appear in `eval.metadata.condition`, the model events, returned outputs, and stored triage results. The outer placeholder is not evidence that these 32 live responses were mocked. Conversely, that outer configuration is not a complete provider configuration record.

Both native evaluations record `log_model_api: false`. They preserve normalized Inspect events and messages, not the exact outgoing HTTP request bodies. Wire-level serialization, provider-specific schema enforcement, API selection, and adapter defaults require the separate source/configuration audit; this document does not silently infer those settings from missing log fields.

### Later histories and final-turn behavior were not identical

The same final-turn reminder text is observed in 14 OpenAI trajectories and nine Anthropic trajectories:

```text
The investigation budget is exhausted. Return the final JSON decision now.
```

Those trajectories reach generation five and record `tool_choice: "none"`. The remaining two OpenAI and seven Anthropic trajectories finish earlier with final `tool_choice: "auto"` and no extra user reminder.

All nine directly fenced Haiku responses belong to the reminder group; all seven analysis-prefixed responses belong to the earlier-finish group. This is an observed association, not an experiment showing that the reminder caused either format. Alert identity, chosen tools, conversation length, and final-turn handling vary together. The reminder did not produce an accepted bare-JSON response in any Haiku trajectory.

There is also a recorded final-event tool-list difference: OpenAI's 14 forced-final events have `tools: []`, while Anthropic retains all four tool definitions in all 72 model events, including its nine `tool_choice: "none"` finals. Their initial tool definitions match, but normalized final requests differ. This alone does not identify a defect or establish its effect on output formatting; provider-adapter semantics must be checked separately.

## What run 1 can and cannot establish

Run 1 establishes that the original integrated OpenAI condition satisfied the strict output contract on 16/16 of these DEV trajectories, while the original integrated Anthropic condition satisfied it on 0/16. Under the frozen scorer for that run, OpenAI also matched all reference triage actions and severities, with 13/16 acceptable technique IDs. Those original observations and assigned scores are preserved.

Reading the 16/16-versus-0/16 score as a general model-quality result is too strong. Haiku's action, severity, technique, and citation scoring never received a parsed decision. Its zero all-case accuracies and maximum invalid-action cost are dominated by one output-contract failure mode. They do not measure 16 independent failures of SOC reasoning, nor does a zero false-benign counter establish safety when there are no valid decisions. Its severity MAE remains unavailable with a valid denominator of zero.

Identical initial text is useful evidence of fairness at that boundary, but it is insufficient to claim equivalent structured-output enforcement across provider APIs. Later tool evidence and conversations differ by model choice, final reminders occur with different frequency, one recorded reasoning setting differs, and final tool-list handling differs. Native logs alone cannot assign the failure solely to model capability, provider configuration, or harness integration. They also do not prove that either provider lacked or received equivalent native structured-output enforcement.

The paired family-bootstrap intervals quantify the already assigned contract-based scores on eight authored DEV families. They do not resolve these configuration and construct-validity limits or rank general SOC quality. The degenerate action interval reflects the same assigned score difference in every observed pair, not certainty about future alerts or reasoning ability.

The prior recommendation to use the 16/16 condition as a development baseline must therefore be read as a bounded engineering observation about that configuration. It is not a validated quality ranking. A comparison using equivalent, explicitly recorded structured-output mechanisms is a new condition and requires a separately identified slice run; it must not overwrite, repair, or merge away run 1. No claim about that later run is made here. Neither operational readiness nor semantic faithfulness is established, and the human calibration responses remain unlabeled by this audit.

## Full original raw responses

These three examples are selected to show both observed output formats while using IDs outside the predeclared 20-response human-calibration selection. They are evidence excerpts, not examples chosen for correctness. The outer four-backtick fences below delimit this document's quotations; the inner Markdown, JSON text, and prose are the full original `raw_output` strings. Hashes refer to those original strings, excluding the documentary delimiters. Quoted claims are not semantically graded here.

### A001 — analysis prefix, then fenced JSON

- Full raw string: 2445 characters / 2449 UTF-8 bytes.
- SHA-256: `dd3c49136bcb7dabe5048671bee56c4cb9dff2689f1d6cfad3d84e7a2eaa96c5`.
- Stored parser error: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
- 4 generations; 3 tools; final native stop `stop`; 605 final output tokens; final tool choice `auto`.

````text
## Analysis

**Alert Summary:**
The alert detected a large outbound archive transfer (268 MB) from host `backup-01` via HTTPS to IP `203.0.113.58` using the signed `backup-agent.exe` process under the service account `svc-backup01`.

**Evidence Review:**

1. **Host Context (host:backup-01):** Change approval CHG-1010 explicitly authorizes backup-job-10 using backup-agent.exe to destination 203.0.113.58 at the alert timestamp. The observed transfer size (268 MB) falls within the expected 200–300 MiB range for this job.

2. **User Context (user:svc-backup01):** This is a noninteractive service identity configured specifically for backup-job-10, consistent with an automated scheduled backup.

3. **Process Integrity:** The backup-agent.exe binary is signed with valid signature, running under its parent service-manager, indicating legitimate execution.

4. **Network Characteristics:** HTTPS protocol, encrypted content (backup archive), completed transfer status, and a well-formed job ID all align with standard backup operations.

5. **IP Reputation (ip:203.0.113.58):** The destination is the configured backup service endpoint with no incident indicators in the offline fixture.

**Conclusion:**
All indicators point to legitimate, authorized scheduled backup activity. The change approval explicitly authorizes this exact operation, the service account and process are appropriate, and the transfer characteristics match baseline expectations.

```json
{"verdict":"benign","severity":4,"technique_id":null,"summary":"Authorized scheduled backup job (CHG-1010) transferring data to configured backup destination. Process is signed, user is noninteractive service account, transfer size within expected range, and destination has no incident indicators.","evidence":[{"source_id":"host:backup-01","fact":"CHG-1010 approves backup-job-10 using backup-agent.exe to 203.0.113.58 at alert timestamp"},{"source_id":"host:backup-01","fact":"Observed transfer size 268 MB is within recorded 200–300 MiB expected range"},{"source_id":"user:svc-backup01","fact":"svc-backup01 is noninteractive identity for backup-job-10"},{"source_id":"alert:A001","fact":"backup-agent.exe process is signed with valid signature"},{"source_id":"alert:A001","fact":"Transfer completed via HTTPS with encrypted backup archive contents"},{"source_id":"ip:203.0.113.58","fact":"Destination is configured backup service endpoint with no incident indicators"}]}
```
````

### A006 — analysis prefix, then fenced JSON

- Full raw string: 2286 characters / 2286 UTF-8 bytes.
- SHA-256: `4c7d8f470e907380b7bd6768f8783266a15f3725ae6ca06640f96e4d3a5418bd`.
- Stored parser error: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
- 4 generations; 3 tools; final native stop `stop`; 564 final output tokens; final tool choice `auto`.

````text
## Analysis

The alert reports a successful scheduled task registration with the following key observations:

**Evidence Summary:**
- **Host Context (host:ws-06):** Change request CHG-1008 explicitly approves the creation of "PackageMaintenance" task scheduled daily at 11:00 UTC, running as SYSTEM with the observed signed executable path `C:\Program Files\PackageService\update.exe`. The registration timestamp falls within the approved change window.
- **User Context (user:svc-update06):** The service account is approved to maintain this specific task on ws-06.
- **Event Details:** The task was registered successfully with a valid signature from a signed binary, parent process is update-agent.exe, and the task action is signed.
- **Network:** Destination IP 192.0.2.42 is an internal lab endpoint with no adverse reputation.

**Verdict Rationale:**
All observable evidence points to approved, legitimate administrative activity:
1. An approved change request (CHG-1008) explicitly authorizes this exact task creation
2. The authorized service account performed the action
3. The executable and task signature are valid
4. The timing aligns with the approved change window
5. The task configuration matches the approval exactly

This is clearly a benign, authorized operation being detected by the sensor's rules.

```json
{"verdict":"benign","severity":4,"technique_id":null,"summary":"Scheduled task registration matches approved change CHG-1008; authorized service account (svc-update06) created PackageMaintenance task with valid signature on approved host within change window.","evidence":[{"source_id":"host:ws-06","fact":"CHG-1008 approves PackageMaintenance daily at 11:00 UTC, run as SYSTEM, with the observed signed path"},{"source_id":"host:ws-06","fact":"Task registration timestamp 2026-11-10T10:06:00Z falls within approved change window"},{"source_id":"user:svc-update06","fact":"Service identity svc-update06 is approved to maintain PackageMaintenance task on ws-06"},{"source_id":"alert:A006","fact":"Task action signed and signature valid"},{"source_id":"alert:A006","fact":"Task action path is C:\\Program Files\\PackageService\\update.exe"},{"source_id":"ip:192.0.2.42","fact":"Destination address is internal lab endpoint with no adverse reputation"}]}
```
````

### A015 — direct Markdown JSON fence

- Full raw string: 2036 characters / 2036 UTF-8 bytes.
- SHA-256: `06be9f93df94db1f2a7f83d3b4e39b9d0eb90b102b1db876f9dd367135118985`.
- Stored parser error: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
- 5 generations; 4 tools; final native stop `stop`; 531 final output tokens; final tool choice `none`.

````text
```json
{
  "verdict": "needs_escalation",
  "severity": 2,
  "technique_id": null,
  "summary": "75 authentication failures across 25 distinct accounts from a shared egress IP (browser-isolation service) within 15 minutes cannot be attributed to a specific attacker or authorized activity. Client identifiers were not retained in the aggregation, preventing attribution to individual users or sessions. No successful authentications occurred in the window. The approved egress address does not establish that each attempt was authorized. Client-level records and session details are required to distinguish between credential spraying, password testing, legitimate bulk access, or misconfiguration.",
  "evidence": [
    {
      "source_id": "alert:A015",
      "fact": "75 failed authentication attempts across 25 distinct accounts in 15-minute window via HTTPS sign-in protocol"
    },
    {
      "source_id": "alert:A015",
      "fact": "No successful authentications recorded; no candidate password count retained"
    },
    {
      "source_id": "alert:A015",
      "fact": "Client identifiers were not retained (client_identifiers_retained: false)"
    },
    {
      "source_id": "ip:203.0.113.45",
      "fact": "Source IP is a shared egress point used by an approved browser-isolation service"
    },
    {
      "source_id": "ip:203.0.113.45",
      "fact": "Reputation record has no per-client session mapping and cannot identify the originator of sign-in attempts"
    },
    {
      "source_id": "host:auth-15",
      "fact": "Identity gateway did not retain client identifiers in this source-address aggregate"
    },
    {
      "source_id": "RB06",
      "fact": "Runbook guidance: repeated failure alone does not establish credential spraying pattern without password candidate cardinality"
    },
    {
      "source_id": "RB07",
      "fact": "Runbook guidance: approved egress address does not prove each action was approved; client-level records required when aggregation lacks client identifiers"
    }
  ]
}
```
````
