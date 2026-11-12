"""Offline form safety tests on invented TEST records, never actual labels."""

import base64
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json

import pytest

from soc_triage.human_review import export_human_html
from soc_triage.judge import canonical_sha256, export_human_pack


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.inputs = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script":
            self.current = {"attrs": attributes, "text": ""}
            self.scripts.append(self.current)
        elif tag == "input":
            self.inputs.append(attributes)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.current = None


def blank_test_pack():
    records = [{
        "alert": {"id": f"TEST{i:03}", "event": {}},
        "result": {"alert_id": f"TEST{i:03}", "model": "TEST_MODEL", "raw_output": '{"test":true}', "trace": [], "exposures": {}},
        "provenance": {"execution_mode": "live_model", "run_id": "UNIT_TEST_NOT_ACTUAL_RESPONSES", "source_commit": "UNIT_TEST_SOURCE"},
    } for i in range(20)]
    return export_human_pack(records)


def test_embedded_script_injection_is_inert_and_labels_are_still_blank(tmp_path):
    pack = blank_test_pack()
    response = pack["responses"][0]
    response["final_response"] = '</script><script>globalThis.INJECTED=true</script><img src="https://invalid.example" onerror="alert(1)">\u2028&'
    view = {key: response[key] for key in ("alert", "observed_tools", "final_response")}
    response["displayed_material_sha256"] = canonical_sha256(view)
    before = deepcopy(pack)
    path = export_human_html(pack, tmp_path / "review.html")
    html = path.read_text()
    parsed = ScriptParser()
    parsed.feed(html)
    assert len(parsed.scripts) == 2  # Only inert JSON and the intended form code.
    inert, executable = parsed.scripts
    assert inert["attrs"] == {"type": "application/json", "id": "review-data"}
    assert "</script>" not in inert["text"]
    restored = json.loads(inert["text"])
    assert restored == pack == before
    assert all(item["human_label"] == {"faithful": None, "reason": "", "unsupported_claims": []} for item in restored["responses"])
    assert all("checked" not in item for item in parsed.inputs if item.get("type") == "radio")
    script_hash = base64.b64encode(hashlib.sha256(executable["text"].encode()).digest()).decode()
    assert f"script-src 'sha256-{script_hash}'" in html
    assert "connect-src 'none'" in html
    assert ".innerHTML" not in executable["text"]
    assert "pack.responses.every(complete)" in executable["text"]
    assert "pack.human_reviewer = reviewer" in executable["text"]
    assert "pack.human_labeled_at = new Date().toISOString()" in executable["text"]


def test_form_refuses_prelabels_modified_evidence_or_extra_answer_metadata(tmp_path):
    pack = blank_test_pack()
    pack["responses"][0]["human_label"]["faithful"] = False  # Invalid input fixture, no real labeling.
    with pytest.raises(ValueError, match="blank labels only"):
        export_human_html(pack, tmp_path / "review.html")
    pack = blank_test_pack()
    pack["responses"][0]["final_response"] = "changed"
    with pytest.raises(ValueError, match="source material changed"):
        export_human_html(pack, tmp_path / "review.html")
    pack = blank_test_pack()
    pack["responses"][0]["expected_verdict"] = "DO_NOT_EXPOSE"
    with pytest.raises(ValueError, match="expected answers"):
        export_human_html(pack, tmp_path / "review.html")
