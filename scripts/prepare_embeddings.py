"""Explicitly acquire checksum-pinned public weights; evaluation stays offline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request


def main() -> None:
    manifest = json.loads(Path("config/embedding.json").read_text())
    root = Path(".cache/model2vec")
    root.mkdir(parents=True, exist_ok=True)
    for filename, expected in manifest["files"].items():
        if Path(filename).name != filename:
            raise ValueError("Unexpected asset path")
        destination = root / filename
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
            continue
        url = f"https://huggingface.co/{manifest['model_id']}/resolve/{manifest['revision']}/{filename}"
        request = urllib.request.Request(url, headers={"User-Agent": "soc-triage-evals-asset-preparation"})
        data = urllib.request.urlopen(request, timeout=90).read(32 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for {filename}")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
    print(f"Verified {manifest['model_id']} at {manifest['revision']}; runtime uses local files.")


if __name__ == "__main__":
    main()
