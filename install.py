"""Cross-platform source-checkout local installer."""
import signal
from pathlib import Path

from safe_repo_export.installer import interrupt_install, main

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_install)
    raise SystemExit(main(project=Path(__file__).resolve().parent))
