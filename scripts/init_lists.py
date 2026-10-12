"""Write default policy lists into the caller's current Git repository."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safe_repo_export.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["init", *sys.argv[1:]]))
