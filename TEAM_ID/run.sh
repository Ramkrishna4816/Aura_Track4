#!/usr/bin/env bash
# Usage: ./run.sh <video.mp4> <out.json>
# Works from any current directory; relative video/output paths are resolved
# against the caller's directory (this script never changes directory).
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: ./run.sh <video.mp4> <out.json>" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Interpreter: $PYTHON if set, else the first of python3/python that actually runs
# (skips e.g. the Windows Store stub that exists but cannot execute).
PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "pass" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "error: no working Python interpreter found (set PYTHON=/path/to/python)" >&2
  exit 127
fi

exec "$PYTHON_BIN" "$HERE/code/run_aura.py" "$1" "$2"
