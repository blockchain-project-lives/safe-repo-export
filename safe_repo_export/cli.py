"""Public command-line interface."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import __version__, engine
from .exporter import DEFAULT_POLICIES, POLICIES, ExportError, export, git


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="safe-repo-export",
        description="Filter and sanitize a Git commit or working tree for sharing or code analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Commands:
  init                  Write default .list files to the current repository's
                        .safe-repo-export/ directory; preserve existing files.
  init-policies         Alias for init.

Examples:
  safe-repo-export --output ../sanitized --archive zip
  safe-repo-export --worktree --output ../sanitized --replace
  safe-repo-export init
  safe-repo-export init --help
  safe-repo-export init --directory /path/to/project/.safe-repo-export

Defaults: current repository, HEAD, no archive. --output is required for export.
Commit edited repository policies before exporting, or use --worktree.""",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--repo", default=".", help="Source Git repository (default: current directory)")
    parser.add_argument("--ref", default="HEAD", help="Commit, branch or tag (default: HEAD)")
    parser.add_argument("--output", required=True, help="Output directory outside the source repository")
    parser.add_argument("--archive", choices=["none", "zip", "tar.gz"], default="none")
    parser.add_argument("--replace", action="store_true", help="Replace differing output and archives with rollback on failure")
    parser.add_argument("--worktree", action="store_true", help="Export current tracked working files and policies, including staged/unstaged edits; requires HEAD")
    parser.add_argument("--allow-dirty", action="store_true", help="Ignore tracked edits; only committed content is exported")
    parser.add_argument("--require-gitleaks", action="store_true")
    parser.add_argument("--gitleaks-strict", action="store_true", help="Require Gitleaks and block on findings/errors")
    parser.add_argument("--salt-file", help="Private persistent salt (default: OUTPUT.pseudonym-salt)")
    for option, filename in POLICIES.items():
        parser.add_argument("--" + option.replace("_", "-"), help=f"Override {filename}")
    return parser


def default_policy_directory() -> Path:
    root = Path.cwd()
    if shutil.which("git"):
        try:
            root = Path(git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        except ExportError:
            pass  # Policy preparation is also useful before git init.
    return root / ".safe-repo-export"


def init_policies(argv: list[str], *, prog: str = "safe-repo-export init") -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Write the six bundled .list templates; existing files are preserved.",
    )
    parser.add_argument(
        "--directory", metavar="PATH",
        help="Destination (default: current Git repository root/.safe-repo-export; current directory before git init)",
    )
    args = parser.parse_args(argv)
    destination = Path(args.directory).expanduser() if args.directory is not None else default_policy_directory()
    if destination.is_symlink():
        raise ExportError("Policy directory must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for filename in POLICIES.values():
        try:
            with (destination / filename).open("xb") as output:
                output.write((DEFAULT_POLICIES / filename).read_bytes())
            print(f"Created policy: {filename}")
        except FileExistsError:
            print(f"Kept existing policy: {filename}")
    print(f"Policies: {destination.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if not argv:
            build_parser().print_help()
            return 0
        if argv[0] in {"init", "init-policies"}:
            return init_policies(argv[1:], prog=f"safe-repo-export {argv[0]}")
        if argv and argv[0] in {"sanitize", "generate-salt", "summarize-gitleaks", "finalize"}:
            args = engine.build_parser().parse_args(argv)
            return int(args.func(args))
        export(build_parser().parse_args(argv))
        return 0
    except (ExportError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: Export interrupted", file=sys.stderr)
        return 130
