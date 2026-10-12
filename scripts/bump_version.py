"""Source checkout entry point for one-command version updates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safe_repo_export.release import main

if __name__ == "__main__":
    raise SystemExit(main())
