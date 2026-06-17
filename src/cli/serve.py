"""Start local web UI."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from web.app import main as run_app
    except ImportError as exc:
        print(
            "Dipendenze web mancanti. Installa con:\n"
            "  py -3 -m pip install -e \".[web]\"",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
