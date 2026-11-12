# Synthetic SOC triage development dataset

This is a **16-alert vertical-slice development dataset**, not a held-out test set or evidence of production detection quality. All events, people, hosts, approvals, interviews, indicators, timestamps and context records are original synthetic material. No customer records, company telemetry, real credentials or attack execution were used. Recorded command lines are inert observations; omitted payloads are not executable examples.

The slice includes eight behavior families, six benign events, two events whose truth remains unknown, and eight malicious events. Seven malicious events have the `true_positive` triage disposition; one requires `needs_escalation` under the critical-asset export policy. These labels are **design-time synthetic reference judgments**, not independently human-validated observations. They do not supply faithfulness-calibration labels.

## Scope and partitions

All 16 cases are development material. Do not describe a sample of them, a recorded-response replay, or their family bootstrap as an independent test. The two variants of a family deliberately share behavioral assumptions and are not independent examples. Identifiers, placeholder address ranges and timestamps are not label rules.

The future full dataset may use a 70/30 development/test split grouped by `family_id`, with every variant of an underlying family in one partition. That full split is **not implemented here**. Do not expand this slice to 120–150 alerts or claim a formal held-out result without separately completing that work. Ten fixed development cases can exercise a live integration without becoming a held-out benchmark: `A002`, `A004`, `A005`, `A007`, `A009`, `A010`, `A011`, `A012`, `A013`, `A014`. This selection covers all eight families, a self-contained no-tool benign event and an uncertain escalation.

## Files and visibility

| Path | Purpose | Model-visible |
| --- | --- | --- |
| `data/alerts/A001.json` … `A016.json` | One alert per JSON object | Yes, selected alert only |
| `data/tool_context/context.json` | Deterministic offline IP, user and host facts | Only records returned by an allowed tool |
| `runbooks/RB01.md` … `RB30.md` | Short original guidance, with frontmatter IDs | Only retrieved documents |
| `data/references/A001.json` … `A016.json` | Expected decisions, facts and tool policies | **No; evaluation only** |
| `DATASET.md` | Authoring, policy and provenance documentation | No agent input |

Alert objects contain `id`, neutral `family_id`, `source`, `rule`, `host`, `user`, `source_ip`, `destination_ip`, `process` (`name`, `command_line`, `parent`), `timestamp`, and an event-specific `event` object. Their implicit evidence identifier is `alert:<id>`, for example `alert:A002`. They contain no reference labels, severity target, technique target or expected tool policy.

The tool-context top-level keys are `ip_reputation`, `user_context` and `host_context`. Each entity record contains a literal `source_id`, `facts`, `as_of` and `origin`. Tools must preserve the source identifier: `ip:<address>`, `user:<username>`, or `host:<hostname>`. The 30 runbooks use IDs `RB01`–`RB30`. Context is authored once and read offline; tools must not query live reputation services, directories or hosts. All IP addresses are within documentation ranges `192.0.2.0/24`, `198.51.100.0/24` and `203.0.113.0/24`; event domains end in `example.invalid`.

## Reference and decision policy

Reference objects contain `alert_id`, `family_id`, `event_truth`, `expected_verdict`, `severity`, `acceptable_technique_ids`, `required_facts`, `tool_policy`, `max_tool_calls` and `notes`. A required fact has a stable `id`, original prose `fact`, and resolvable `supporting_ids`. No recorded response oracle or reference answer is embedded.

`event_truth` describes the underlying event in this synthetic scenario:

- `malicious`: retained behavior and scoped context establish unauthorized adversarial activity.
- `benign`: affirmative evidence matches the observed action to approved activity and its scope.
- `unknown`: the retained evidence does not resolve attack versus authorized activity. Missing context is not a benign label.

`expected_verdict` is the triage disposition, independently of event truth:

- `true_positive`: adversarial activity is evidenced and no specific review rule changes the disposition.
- `benign`: evidence affirmatively matches the action, identity, host, destination and time as applicable to authorized routine work.
- `needs_escalation`: either decisive evidence is unavailable or a specific review policy requires incident-lead judgment. `A012` is deliberately malicious with a supported technique, while still requiring escalation under `RB18` for unauthorized restricted-data export from a critical asset. `A010` and `A015` require escalation because event truth remains unresolved.

Severity follows `RB02`: **1 critical**, **2 high**, **3 medium**, **4 low**. Severity 1 covers observed restricted-data export from a critical asset or completed credential-memory capture on a critical identity host. Severity 2 covers evidenced unauthorized remote control, account use, persistence, protection impairment or tool transfer without that critical impact. Severity 3 denotes an unresolved anomaly requiring review. Severity 4 denotes narrowly verified routine authorized activity. These priorities are a lab policy, not a universal industry severity standard.

Technique references are specific adversarial-behavior mappings, not names for every legitimate use of a utility. Benign cases and unresolved anomalies use `[null]` when an attack mapping is not established. Do not infer dumping from a metadata query, spraying from aggregated failures, account abuse from location alone, exfiltration over C2 from volume alone, or execution from a completed download.

`tool_policy.required_any_of` is a conjunction of alternatives: satisfy at least one tool in **each** inner list. An empty outer list requires no tool. `optional` tools may help but are not mandatory. `forbidden` tools are unnecessary for that case and count as policy violations if called. The universe is `ip_reputation`, `user_context`, `host_context`, `runbook_search`; every reference assigns every tool to a category. There is a six-call limit. `A011` already carries complete scoped inventory authorization, so all four tools are forbidden. `A012` needs host criticality, IP/session context and retrieval of the critical-asset review policy. Tools collectively resolve genuine evidence or policy gaps across the slice.

## Case inventory and MITRE ATT&CK® references

The eight mappings below were checked against the linked official MITRE pages on 2026-11-12. Technique names and IDs locate the public source; case narratives and runbooks are original.

| Family | Cases and intended contrast | Technique source |
| --- | --- | --- |
| `powershell-process` | A004 unauthorized script/remote control; A011 approved inventory script | [PowerShell, T1059.001](https://attack.mitre.org/techniques/T1059/001/) |
| `auth-fanout` | A002 single-candidate fanout with denied successful session; A015 unresolved shared-egress aggregation | [Password Spraying, T1110.003](https://attack.mitre.org/techniques/T1110/003/) |
| `process-memory-access` | A009 unauthorized memory read and dump; A003 approved limited metadata query | [LSASS Memory, T1003.001](https://attack.mitre.org/techniques/T1003/001/) |
| `scheduled-task-write` | A014 unauthorized recurring privileged execution; A006 scoped package maintenance | [Scheduled Task, T1053.005](https://attack.mitre.org/techniques/T1053/005/) |
| `outbound-archive-stream` | A012 restricted archive on a control session; A001 approved backup | [Exfiltration Over C2 Channel, T1041](https://attack.mitre.org/techniques/T1041/) |
| `remote-account-session` | A007 confirmed owner-denied session; A010 unresolved new-location session | [Valid Accounts, T1078](https://attack.mitre.org/techniques/T1078/) |
| `security-service-state` | A005 unauthorized stop and startup disable; A016 completed approved upgrade | [Disable or Modify Tools, T1685](https://attack.mitre.org/techniques/T1685/) |
| `external-file-transfer` | A013 unauthorized incoming utility; A008 approved signed package | [Ingress Tool Transfer, T1105](https://attack.mitre.org/techniques/T1105/) |

The current Disable or Modify Tools page uses `T1685`; the historical `T1562.001` identifier is intentionally not used as a current target. This is a narrow behavior slice, not a claim of comprehensive ATT&CK coverage.

## Human calibration boundary

Only a human may label the 20 faithfulness-calibration responses. Dataset references are synthetic scenario ground truth and do not replace that human task. Do not generate, infer or prefill human faithfulness labels from these references, scorer outputs or a judge model. Until the human supplies all required labels, judge calibration is pending. This dataset authoring step does not touch `judge_calibration/`.

## Provenance and rights

The synthetic alert narratives, context fixtures, reference judgments and runbooks are original project material released under the repository's MIT license. No proprietary telemetry, private project material, extracted credential contents or real company/customer data is included. The public references were used to check behavior taxonomy, not to copy procedure examples or operational payloads.

MITRE ATT&CK and ATT&CK are registered trademarks of The MITRE Corporation. This independent lab has no MITRE affiliation or endorsement. MITRE material remains subject to MITRE's [Terms of Use](https://attack.mitre.org/resources/legal-and-branding/terms-of-use/) and [branding guidance](https://attack.mitre.org/resources/legal-and-branding/); it is not relicensed under this project's MIT license. The official terms grant royalty-free research, development and commercial use and specify notice/license requirements for copies. No ATT&CK dataset, technique descriptions or procedure-example corpus is bundled here; the authoritative materials remain at the cited URLs.

© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation.

The notice above identifies the referenced taxonomy material; the original synthetic records and operational lab policy are the responsibility of this project. Recheck official technique pages and terms before refreshing the taxonomy or redistributing additional MITRE content.
