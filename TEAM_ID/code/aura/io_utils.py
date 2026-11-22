"""Strict JSON serialization and atomic file writing."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import config


def dumps_output(data: Any) -> str:
    """Serialize to strict JSON. NaN/Infinity raise ValueError (allow_nan=False)."""
    return json.dumps(data, indent=config.JSON_INDENT, allow_nan=False)


def atomic_write_text(path: "str | os.PathLike[str]", text: str) -> None:
    """Write `text` to `path` so readers see either the old file or the full new
    one, never a partial file. Uses a temp file in the same directory plus
    os.replace. UTF-8 with LF newlines on every OS. Cleans up on any failure and
    leaves a pre-existing target untouched."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_output_json(path: "str | os.PathLike[str]", data: Any) -> None:
    """Serialize strictly first, then write atomically (nothing is written if
    serialization fails)."""
    atomic_write_text(path, dumps_output(data) + "\n")
