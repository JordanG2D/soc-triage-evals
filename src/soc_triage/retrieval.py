"""Small, local-only semantic runbook retrieval with explicit provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol, Sequence

import numpy as np
import yaml

MODEL_ID = "minishlab/potion-base-2M"
MODEL_REVISION = "389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da"


class Encoder(Protocol):
    def encode(self, sentences: Sequence[str]) -> np.ndarray: ...


class LocalEmbeddingModel:
    """Load acquired Model2Vec weights without permitting a network fallback."""

    def __init__(self, model_path: str | Path, manifest_path: str | Path = "config/embedding.json"):
        from model2vec import StaticModel

        self.model_path = Path(model_path).resolve()
        required = ("config.json", "tokenizer.json", "model.safetensors")
        for filename in required:
            if not (self.model_path / filename).is_file():
                raise FileNotFoundError(
                    f"Missing local embedding asset {filename}; acquire the pinned model first"
                )
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if manifest.get("model_id") != MODEL_ID or manifest.get("revision") != MODEL_REVISION:
            raise ValueError("Embedding manifest does not match the declared model revision")
        for filename in required:
            expected = manifest.get("files", {}).get(filename, "")
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError(f"Embedding manifest lacks a valid checksum for {filename}")
            actual = hashlib.sha256((self.model_path / filename).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Embedding asset checksum mismatch: {filename}")
        self.provenance = manifest
        # A resolved directory is passed, never a hub ID. Model2Vec loads existing
        # files directly; there is no implicit model download in this code path.
        self._model = StaticModel.from_pretrained(str(self.model_path), force_download=False)

    def encode(self, sentences: Sequence[str]) -> np.ndarray:
        return np.asarray(self._model.encode(list(sentences)), dtype=np.float32)


@dataclass(frozen=True)
class Runbook:
    source_id: str
    title: str
    text: str
    path: str


@dataclass(frozen=True)
class RetrievalHit:
    source_id: str
    title: str
    text: str
    path: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def load_runbooks(directory: str | Path) -> list[Runbook]:
    books: list[Runbook] = []
    seen: set[str] = set()
    for path in sorted(Path(directory).glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            raise ValueError(f"Runbook lacks YAML frontmatter: {path.name}")
        parts = raw.split("---", 2)
        metadata = yaml.safe_load(parts[1])
        source_id = str(metadata["id"])
        if source_id in seen:
            raise ValueError(f"Duplicate runbook source ID: {source_id}")
        seen.add(source_id)
        text = parts[2].strip()
        title = str(metadata.get("title") or text.splitlines()[0].lstrip("# "))
        books.append(Runbook(source_id, title, text, path.name))
    if not books:
        raise ValueError("No runbooks found")
    return books


def _unit_rows(array: np.ndarray) -> np.ndarray:
    array = np.asarray(array, dtype=np.float32)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError("Encoder must return a finite two-dimensional matrix")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return np.divide(array, norms, out=np.zeros_like(array), where=norms != 0)


class LocalRunbookIndex:
    """An in-memory cosine vector index, rebuilt from the declared runbook set."""

    def __init__(self, runbooks: Sequence[Runbook], encoder: Encoder):
        if not runbooks:
            raise ValueError("Cannot index an empty runbook set")
        if len({b.source_id for b in runbooks}) != len(runbooks):
            raise ValueError("Runbook source IDs must be unique")
        self.runbooks = tuple(runbooks)
        self.encoder = encoder
        self.provenance = getattr(encoder, "provenance", {"encoder": "injected"})
        self.vectors = _unit_rows(encoder.encode([b.title + "\n" + b.text for b in runbooks]))
        if len(self.vectors) != len(runbooks):
            raise ValueError("Encoder returned the wrong number of vectors")

    @classmethod
    def from_directory(cls, directory: str | Path, model_path: str | Path) -> "LocalRunbookIndex":
        return cls(load_runbooks(directory), LocalEmbeddingModel(model_path))

    def search(self, query: str, top_k: int = 3) -> list[RetrievalHit]:
        if not query.strip() or len(query) > 2000:
            raise ValueError("Query must contain 1–2000 characters")
        if isinstance(top_k, bool) or not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")
        vector = _unit_rows(self.encoder.encode([query]))
        if vector.shape != (1, self.vectors.shape[1]):
            raise ValueError("Query embedding has an incompatible shape")
        scores = self.vectors @ vector[0]
        # Stable tie-breaking preserves reproducibility across repeated runs.
        order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.runbooks[i].source_id))
        return [
            RetrievalHit(**asdict(self.runbooks[i]), score=round(float(scores[i]), 8))
            for i in order[:top_k]
        ]
