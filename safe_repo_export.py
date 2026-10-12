#!/usr/bin/env python3
"""Source checkout entry point; prefer python -m safe_repo_export."""
from safe_repo_export.engine import *  # noqa: F401,F403

if __name__ == "__main__":
    from safe_repo_export.cli import main
    raise SystemExit(main())
