"""Cosine ranking, provenance and local-only acquisition boundaries."""

import os
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from soc_triage.retrieval import MODEL_ID, MODEL_REVISION, LocalEmbeddingModel, LocalRunbookIndex, Runbook, load_runbooks


class NumericEncoder:
    """A test double for checking vector-index math, not semantic acceptance."""

    def encode(self, sentences):
        values = {
            "PowerShell\nEncoded command": [3.0, 0.0],
            "Identity\nImpossible travel": [0.0, 5.0],
            "script investigation": [2.0, 0.1],
        }
        return np.asarray([values[text] for text in sentences], dtype=np.float32)


def test_cosine_ranking_exposes_actual_source_text():
    index = LocalRunbookIndex([
        Runbook("RB02", "Identity", "Impossible travel", "identity.md"),
        Runbook("RB01", "PowerShell", "Encoded command", "powershell.md"),
    ], NumericEncoder())
    hits = index.search("script investigation", 2)
    assert [hit.source_id for hit in hits] == ["RB01", "RB02"]
    assert hits[0].score > 0.99
    assert hits[0].to_dict()["text"] == "Encoded command"
    assert hits[0].path == "powershell.md"


def test_missing_weights_fails_before_a_hub_load(tmp_path, monkeypatch):
    import model2vec

    def forbidden(*args, **kwargs):
        raise AssertionError("A missing local model must not trigger model loading")

    monkeypatch.setattr(model2vec.StaticModel, "from_pretrained", forbidden)
    with pytest.raises(FileNotFoundError, match="Missing local embedding asset"):
        LocalEmbeddingModel(tmp_path)


def test_duplicate_provenance_is_rejected(tmp_path):
    for name in ("one.md", "two.md"):
        (tmp_path / name).write_text("---\nid: RB01\n---\n# A runbook\nProcedure.")
    with pytest.raises(ValueError, match="Duplicate runbook source ID"):
        load_runbooks(tmp_path)


def test_changed_weight_bytes_are_rejected_before_inference(tmp_path, monkeypatch):
    import model2vec

    files = {}
    for filename in ("config.json", "tokenizer.json", "model.safetensors"):
        (tmp_path / filename).write_bytes(b"original")
        files[filename] = hashlib.sha256(b"original").hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": files}))
    (tmp_path / "model.safetensors").write_bytes(b"changed")
    monkeypatch.setattr(model2vec.StaticModel, "from_pretrained", lambda *args, **kwargs: pytest.fail("Must not load changed weights"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        LocalEmbeddingModel(tmp_path, manifest)


def test_real_local_semantic_embedding_when_acquired():
    """No downloads: CI may acquire the pinned assets in an explicit earlier step."""

    model_path = Path(os.environ.get("SOC_EMBEDDING_MODEL_PATH", ".cache/model2vec"))
    if not (model_path / "model.safetensors").exists():
        pytest.skip("Pinned embedding weights have not been acquired locally")
    index = LocalRunbookIndex([
        Runbook("RB01", "Credential theft", "A process reads LSASS memory and dumps logon secrets.", "a.md"),
        Runbook("RB02", "Mailbox administration", "An approved inbox forwarding change routes customer mail.", "b.md"),
        Runbook("RB03", "Device inventory", "A scheduled asset scan records workstation disk capacity.", "c.md"),
    ], LocalEmbeddingModel(model_path))
    hits = index.search("investigate stolen passwords and credential dumping", 1)
    assert hits[0].source_id == "RB01"
    assert 0 < hits[0].score <= 1
