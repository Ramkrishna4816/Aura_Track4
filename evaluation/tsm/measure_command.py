"""Record elapsed seconds and peak Linux RSS for one fresh command process."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Sequence


def measure(command: Sequence[str], log: Path) -> dict:
    """Wait for the specific child to obtain its own resource usage."""
    if sys.platform != "linux":
        raise RuntimeError("this benchmark requires Linux resource accounting")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("x", encoding="utf-8") as output:
        started = perf_counter()
        with subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT) as child:
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        elapsed = perf_counter() - started
    return {
        "wall_seconds": round(elapsed, 6),
        "peak_rss_kib": usage.ru_maxrss,
        "exit_code": child.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("supply one command after --")
    if args.measurement.exists() or args.measurement.resolve() == args.log.resolve():
        parser.error("measurement file must be new and distinct from the log")
    try:
        record = measure(command, args.log)
        args.measurement.parent.mkdir(parents=True, exist_ok=True)
        with args.measurement.open("x", encoding="utf-8") as output:
            output.write(json.dumps(record, indent=2, allow_nan=False) + "\n")
    except (OSError, RuntimeError) as exc:
        parser.exit(2, f"{exc}\n")
    return record["exit_code"] if record["exit_code"] >= 0 else 128 - record["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
