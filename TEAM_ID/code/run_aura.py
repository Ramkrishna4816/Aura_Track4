"""Launcher used by run.sh. Running a script puts its own directory (this
`code/` folder) on sys.path, so `aura` is importable regardless of the current
working directory, and nothing here is named like a stdlib module."""
import sys

from aura.main import main

if __name__ == "__main__":
    sys.exit(main())
