"""Export a self-contained offline form for a human's 20 blank labels."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .judge import FAITHFULNESS_RUBRIC, canonical_sha256


_SCRIPT = r"""
"use strict";
const original = JSON.parse(document.getElementById("review-data").textContent);
const pack = structuredClone(original);
let current = 0;
const byId = id => document.getElementById(id);
const choices = Array.from(document.querySelectorAll('input[name="faithful"]'));
function complete(response) {
  const label = response.human_label;
  return typeof label.faithful === "boolean" && label.reason.trim().length > 0;
}
function persist() {
  const label = pack.responses[current].human_label;
  const selected = choices.find(choice => choice.checked);
  label.faithful = selected ? selected.value === "true" : null;
  label.reason = byId("reason").value;
  label.unsupported_claims = byId("unsupported").value.split("\n").map(value => value.trim()).filter(Boolean);
  updateProgress();
}
function updateProgress() {
  const completed = pack.responses.filter(complete).length;
  byId("progress-label").textContent = `${completed} of 20 responses reviewed`;
  byId("progress").value = completed;
  const hasReviewer = byId("reviewer").value.trim().length > 0;
  byId("download").disabled = completed !== 20 || !hasReviewer;
  byId("download-help").textContent = completed === 20 && hasReviewer
    ? "All required human fields are complete. Download your labeled JSON."
    : "Download becomes available after 20 choices, 20 reasons, and your name.";
  for (const button of byId("response-list").children) {
    const index = Number(button.dataset.index);
    button.classList.toggle("done", complete(pack.responses[index]));
    button.setAttribute("aria-current", index === current ? "step" : "false");
    button.title = `${pack.responses[index].response_id}: ${complete(pack.responses[index]) ? "reviewed" : "incomplete"}`;
  }
}
function display(index) {
  current = index;
  const response = pack.responses[index];
  byId("response-title").textContent = `Response ${index + 1} of 20 · ${response.response_id}`;
  byId("alert").textContent = JSON.stringify(response.alert, null, 2);
  byId("tools").textContent = response.observed_tools.length
    ? JSON.stringify(response.observed_tools, null, 2)
    : "No tools were observed for this response. Use the alert and final response only.";
  byId("final").textContent = response.final_response;
  byId("source-hash").textContent = response.source_sha256;
  byId("material-hash").textContent = response.displayed_material_sha256;
  for (const choice of choices) {
    choice.checked = response.human_label.faithful === (choice.value === "true");
  }
  byId("reason").value = response.human_label.reason;
  byId("unsupported").value = response.human_label.unsupported_claims.join("\n");
  byId("previous").disabled = index === 0;
  byId("next").disabled = index === pack.responses.length - 1;
  updateProgress();
}
byId("rubric").textContent = pack.rubric;
for (let index = 0; index < pack.responses.length; index++) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.index = String(index);
  button.textContent = String(index + 1);
  button.addEventListener("click", () => { persist(); display(index); });
  byId("response-list").append(button);
}
for (const choice of choices) choice.addEventListener("change", persist);
byId("reason").addEventListener("input", persist);
byId("unsupported").addEventListener("input", persist);
byId("reviewer").addEventListener("input", updateProgress);
byId("previous").addEventListener("click", () => { persist(); if (current > 0) display(current - 1); });
byId("next").addEventListener("click", () => { persist(); if (current < 19) display(current + 1); });
byId("download").addEventListener("click", () => {
  persist();
  const reviewer = byId("reviewer").value.trim();
  if (!reviewer || pack.responses.length !== 20 || !pack.responses.every(complete)) {
    byId("download-help").textContent = "Complete every required human field before downloading.";
    return;
  }
  pack.human_reviewer = reviewer;
  pack.human_labeled_at = new Date().toISOString();
  const blob = new Blob([JSON.stringify(pack, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "human-calibration-labeled.json";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  byId("download-help").textContent = "Labeled JSON downloaded. Keep this file for judge agreement; no data was sent anywhere.";
});
display(0);
""".strip()


_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src 'none'; script-src 'sha256-__SCRIPT_HASH__'; style-src 'unsafe-inline'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>Human review · 20 development responses</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172b38;background:#edf2f5;line-height:1.5;accent-color:#176a68}
*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:auto;padding:32px 22px 70px}h1{font-size:clamp(1.7rem,4vw,2.4rem);line-height:1.15;margin:10px 0 16px;letter-spacing:-.04em}h2{font-size:1.35rem;margin:0 0 16px}h3{font-size:1rem;margin:0 0 10px}p{margin:8px 0 16px}.eyebrow{font-size:.75rem;letter-spacing:.12em;text-transform:uppercase;color:#176a68;font-weight:750}.intro{max-width:850px;color:#49606c}.card{background:#fff;border:1px solid #d2dde3;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 6px 20px #172b3805}.status{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.status>div{flex:1;min-width:240px}progress{width:100%;height:13px;margin-top:8px}label,.label{display:block;font-weight:650;font-size:.9rem;margin:0 0 7px}input[type=text],textarea{font:inherit;width:100%;border:1px solid #a8bbc5;border-radius:7px;padding:10px 12px;background:#fff;color:#172b38}input:focus-visible,textarea:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #d6a848;outline-offset:3px}textarea{resize:vertical;min-height:100px}.muted{font-size:.86rem;color:#5d717c}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid .card{margin:0}.full{grid-column:1/-1}pre{font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;background:#f4f7f9;padding:16px;border-radius:8px;max-height:480px;overflow:auto}.answer{max-height:580px;border-left:3px solid #176a68}.radio-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0 22px}.radio-option{font-weight:500;border:1px solid #c5d3da;border-radius:10px;padding:15px;cursor:pointer;margin:0}.radio-option input{margin:0 9px 0 0}.radio-option:has(input:checked){border:2px solid #176a68;padding:14px;background:#edf7f5}.radio-option small{display:block;font-weight:400;color:#5d717c;margin:6px 0 0 25px}button{font:inherit;font-weight:650;border:1px solid #a8bbc5;background:#fff;color:#172b38;padding:10px 17px;border-radius:8px;cursor:pointer}button:disabled{opacity:.4;cursor:not-allowed}.primary{background:#176a68;border-color:#176a68;color:white}nav{display:flex;flex-wrap:wrap;gap:7px;margin-top:20px}nav button{width:37px;height:37px;padding:0;font-size:.83rem}nav button.done{background:#e1f2ed;border-color:#77b6a6}nav button[aria-current=step]{outline:2px solid #176a68;outline-offset:2px}summary{font-weight:650;cursor:pointer}details p{margin-top:16px}.hash{font:11px/1.5 ui-monospace,monospace;overflow-wrap:anywhere}.navigation{justify-content:space-between}.required{color:#49606c;font-weight:400;font-size:.82rem}.notice{border-left:3px solid #d6a848;padding-left:13px}.download{margin-top:28px}.field{margin-top:18px}fieldset{margin:0;border:0;padding:0}legend{font-weight:650;padding:0}.footer{margin-top:20px;font-size:.8rem;color:#5d717c}@media(max-width:720px){main{padding:22px 14px 45px}.card{padding:17px}.grid,.radio-grid{grid-template-columns:1fr}.full{grid-column:auto}.status{align-items:stretch}}
</style>
</head>
<body><main>
<header>
<div class="eyebrow">Synthetic development calibration · human review</div>
<h1>Read the evidence.<br>Make your own assessment.</h1>
<p class="intro">Review 20 actual development responses using only each alert and its observed tool results. All choices start blank. The form supplies no expected answers, suggested grades, or model identities.</p>
<p class="muted notice">This file works offline and sends no data. Your work stays in this browser tab until you download the completed JSON. Keep the tab open while reviewing; reloading starts again with blank labels.</p>
</header>
<section class="card" aria-label="Review progress">
<div class="status"><div><strong id="progress-label" aria-live="polite">0 of 20 responses reviewed</strong><progress id="progress" max="20" value="0" aria-label="Responses with a human choice and reason"></progress></div>
<div><label for="reviewer">Your name <span class="required">required for the completed review</span></label><input id="reviewer" type="text" autocomplete="name" placeholder="Human reviewer name" required></div></div>
<nav id="response-list" aria-label="Choose a response"></nav>
</section>
<details class="card"><summary>Read the generic faithfulness rubric</summary><p class="muted">Assess support for factual claims. Expected triage verdict, operational correctness, and completeness are separate questions.</p><pre id="rubric"></pre></details>
<section aria-labelledby="response-title"><h2 id="response-title">Response 1 of 20</h2>
<div class="grid">
<article class="card"><h3>1. Alert received</h3><pre id="alert"></pre></article>
<article class="card"><h3>2. Tools actually observed</h3><pre id="tools"></pre></article>
<article class="card full"><h3>3. Final response to assess</h3><pre id="final" class="answer"></pre></article>
</div>
<section class="card" aria-label="Your assessment">
<fieldset><legend>Your assessment <span class="required">choose one; nothing is preselected</span></legend>
<div class="radio-grid"><label class="radio-option"><input type="radio" name="faithful" value="true">Faithful<small>Every material factual claim is supported, with appropriate uncertainty.</small></label><label class="radio-option"><input type="radio" name="faithful" value="false">Unfaithful<small>At least one material factual claim is unsupported or contradicted.</small></label></div></fieldset>
<label for="reason">Explain your assessment <span class="required">required for every response</span></label><textarea id="reason" placeholder="Point to the observed evidence and explain your decision." required></textarea>
<div class="field"><label for="unsupported">Unsupported claims <span class="required">optional; one claim per line</span></label><textarea id="unsupported" placeholder="List specific unsupported claims, if any."></textarea></div>
</section>
<div class="row navigation"><button id="previous" type="button">← Previous</button><button id="next" type="button">Next →</button></div>
<details class="card"><summary>Source integrity</summary><p class="muted">These identifiers bind this displayed material to its original response record. They are preserved in your download.</p><span class="label">Original record SHA-256</span><p id="source-hash" class="hash"></p><span class="label">Displayed material SHA-256</span><p id="material-hash" class="hash"></p></details>
</section>
<section class="card download"><h2>Download your completed review</h2><p id="download-help" class="muted" aria-live="polite">Download becomes available after 20 choices, 20 reasons, and your name.</p><button id="download" class="primary" type="button" disabled>Download labeled JSON</button><p class="footer">The download preserves all source material and hashes, adds your human labels, and records your name and completion time. No judge runs in this form.</p></section>
<noscript><p class="card">Enable JavaScript to complete this local form. It uses no network requests.</p></noscript>
</main>
<script type="application/json" id="review-data">__PACK_JSON__</script>
<script>__SCRIPT__</script>
</body></html>
"""


def export_human_html(pack: Mapping[str, Any] | str | Path, destination: str | Path) -> Path:
    """Write an offline reviewer for exactly 20 still-blank calibration responses.

    Human choices are collected only in the browser. This function does not
    generate, suggest, preselect, or change any label in the source pack.
    """
    if isinstance(pack, (str, Path)):
        pack = json.loads(Path(pack).read_text())
    if not isinstance(pack, Mapping) or not isinstance(pack.get("responses"), list) or len(pack["responses"]) != 20:
        raise ValueError("offline human review requires the 20-response blank calibration pack")
    if pack.get("rubric") != FAITHFULNESS_RUBRIC:
        raise ValueError("review pack must contain the generic faithfulness rubric")
    allowed = {"response_id", "source_sha256", "displayed_material_sha256", "alert", "observed_tools", "final_response", "human_label"}
    ids = set()
    for response in pack["responses"]:
        if not isinstance(response, Mapping) or set(response) != allowed:
            raise ValueError("unexpected response fields could expose model identity or expected answers")
        response_id = response["response_id"]
        if not isinstance(response_id, str) or response_id in ids:
            raise ValueError("response IDs must be unique strings")
        ids.add(response_id)
        if response["human_label"] != {"faithful": None, "reason": "", "unsupported_claims": []}:
            raise ValueError("human reviewer export accepts blank labels only")
        view = {key: response[key] for key in ("alert", "observed_tools", "final_response")}
        if canonical_sha256(view) != response["displayed_material_sha256"]:
            raise ValueError(f"displayed source material changed for {response_id}")
        source_hash = response["source_sha256"]
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash):
            raise ValueError("original response record hash is required")
    # Escaping '<' prevents any data string from closing its inert JSON script
    # element. Dynamic evidence is inserted solely through DOM textContent.
    serialized = json.dumps(dict(pack), ensure_ascii=False, allow_nan=False)
    for character, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        serialized = serialized.replace(character, escaped)
    script_hash = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
    html = _HTML.replace("__SCRIPT_HASH__", script_hash).replace("__SCRIPT__", _SCRIPT).replace("__PACK_JSON__", serialized)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination
