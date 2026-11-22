#!/usr/bin/env python3
"""Fetch and verify AURA's pinned ONNX model artifacts for offline inference."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

from aura.clip_backend import (
    DEFAULT_WEIGHTS_DIR,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    WEIGHT_ASSETS,
    has_expected_sha256,
)


def _download(url: str, target: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, urlopen(url, timeout=60) as response:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {target.name}")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_weights(weights_dir: Path) -> None:
    """Refresh only missing or corrupt files and replace them after verification."""
    weights_dir = weights_dir.expanduser().resolve()
    weights_dir.mkdir(parents=True, exist_ok=True)
    model_url = f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}"
    for filename, (model_path, digest) in WEIGHT_ASSETS.items():
        target = weights_dir / filename
        if has_expected_sha256(target, digest):
            print(f"Verified {filename}", flush=True)
            continue
        print(f"Downloading {filename}", flush=True)
        _download(f"{model_url}/{model_path}", target, digest)
    print(f"CLIP files ready in {weights_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS_DIR,
                        help="destination directory (default: submission weights/)")
    args = parser.parse_args(argv)
    try:
        fetch_weights(args.weights_dir)
    except (OSError, ValueError) as exc:
        print(f"Could not prepare CLIP weights: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
