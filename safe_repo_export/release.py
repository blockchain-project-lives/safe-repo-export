"""Update the single version source, optionally commit, tag and push a release."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .exporter import ExportError, file_lock

VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ASSIGNMENT_RE = re.compile(r'^__version__ = "(?P<version>[^"\r\n]+)"(?=\r?$)', re.M)
VERSION_PATH = Path("safe_repo_export/_version.py")


class ReleaseError(RuntimeError):
    pass


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ReleaseError(f"Git {args[0]} failed (exit {result.returncode})")
    return result.stdout.decode("utf-8", errors="replace").strip()


def read_version(repo: Path) -> tuple[str, str]:
    if not (repo / "pyproject.toml").is_file():
        raise ReleaseError("Run from the project root or pass --repo PATH")
    text = (repo / VERSION_PATH).read_bytes().decode("utf-8")
    matches = list(ASSIGNMENT_RE.finditer(text))
    if len(matches) != 1 or not VERSION_RE.fullmatch(matches[0]["version"]):
        raise ReleaseError("Version source must contain exactly one X.Y.Z version assignment")
    return text, matches[0]["version"]


def next_version(current: str, change: str) -> str:
    major, minor, patch = map(int, current.split("."))
    if change == "major":
        return f"{major + 1}.0.0"
    if change == "minor":
        return f"{major}.{minor + 1}.0"
    if change == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if not VERSION_RE.fullmatch(change):
        raise ReleaseError("Version must be patch/minor/major or X.Y.Z")
    if tuple(map(int, change.split("."))) <= (major, minor, patch):
        raise ReleaseError("New version must be greater than the current version")
    return change


def check_tag(repo: Path, tag: str) -> str:
    _, version = read_version(repo)
    if tag != f"v{version}":
        raise ReleaseError(f"Tag must match the package version exactly: v{version}")
    print(f"Release version verified: {tag}")
    return version


def update(args) -> str:
    repo = Path(args.repo).expanduser().resolve()
    if args.dry_run:
        return _update_unlocked(args)
    # Store release locks in Git metadata when available, so the lock cannot
    # make an otherwise clean release worktree dirty.
    read_version(repo)
    lock_parent = repo
    if (repo / ".git").is_dir():
        lock_parent = repo / ".git"
    elif (repo / ".git").is_file():
        lock_parent = Path(run_git(repo, "rev-parse", "--absolute-git-dir"))
    with file_lock(lock_parent / "safe-repo-export-version"):
        return _update_unlocked(args)


def _update_unlocked(args) -> str:
    repo = Path(args.repo).expanduser().resolve()
    text, current = read_version(repo)
    version = next_version(current, args.change)
    tag = f"v{version}"
    commit_requested = args.commit or args.tag or args.push
    tag_requested = args.tag or args.push
    branch = None
    if commit_requested:
        if not shutil.which("git"):
            raise ReleaseError("Git is required for commit/tag/push")
        root = Path(run_git(repo, "rev-parse", "--show-toplevel")).resolve()
        if root != repo:
            raise ReleaseError("--repo must be the Git repository root")
        if run_git(repo, "status", "--porcelain"):
            raise ReleaseError("Commit/stash existing changes before a release; only the version file is committed")
        run_git(repo, "rev-parse", "--verify", "HEAD")
        run_git(repo, "var", "GIT_AUTHOR_IDENT")
        run_git(repo, "var", "GIT_COMMITTER_IDENT")
        if tag_requested and run_git(repo, "tag", "--list", tag):
            raise ReleaseError(f"Tag already exists: {tag}")
        if args.push:
            branch = run_git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
            run_git(repo, "remote", "get-url", args.remote)
            if not args.dry_run and run_git(repo, "ls-remote", "--tags", args.remote, f"refs/tags/{tag}"):
                raise ReleaseError(f"Remote tag already exists: {tag}")
    print(f"Version: {current} -> {version}")
    if args.dry_run:
        print(f"Dry run: update {VERSION_PATH.as_posix()}" + (", commit" if commit_requested else "")
              + (f", tag {tag}" if tag_requested else "") + (f", push to {args.remote}" if args.push else ""))
        return version
    path = repo / VERSION_PATH
    if path.is_symlink():
        raise ReleaseError("Version source must not be a symlink")
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("xb") as output:
            output.write(ASSIGNMENT_RE.sub(f'__version__ = "{version}"', text).encode("utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if commit_requested:
        try:
            run_git(repo, "add", "--", VERSION_PATH.as_posix())
            run_git(repo, "commit", "-m", args.message or f"Release {tag}", "--", VERSION_PATH.as_posix())
        except ReleaseError:
            path.write_bytes(text.encode("utf-8"))
            run_git(repo, "restore", "--staged", "--", VERSION_PATH.as_posix())
            raise
    if tag_requested:
        try:
            run_git(repo, "-c", "tag.gpgSign=false", "tag", "-a", tag, "-m", args.message or f"Release {tag}")
        except ReleaseError as exc:
            raise ReleaseError(f"Version commit created; tag creation failed. Create {tag} before publishing") from exc
        print(f"Created tag: {tag}")
    if args.push:
        try:
            # Push only this branch and release tag; either both refs update or neither.
            run_git(repo, "push", "--atomic", args.remote, f"HEAD:refs/heads/{branch}", f"refs/tags/{tag}")
        except ReleaseError as exc:
            raise ReleaseError(f"Local commit and {tag} remain. Retry: git push --atomic {args.remote} HEAD refs/tags/{tag}") from exc
        print(f"Pushed branch and {tag}; the v* tag workflow can publish this release")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("change", nargs="?", help="patch, minor, major or an explicit X.Y.Z")
    parser.add_argument("--repo", default=".", help="Project root (default: current directory)")
    parser.add_argument("--commit", action="store_true", help="Commit only the version source; requires a clean repository")
    parser.add_argument("--tag", action="store_true", help="Commit and create an annotated vX.Y.Z tag")
    parser.add_argument("--push", action="store_true", help="Commit, tag and atomically push the branch and tag")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--message", help="Commit and tag message")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-tag", help="Verify a release tag against the version without changing files")
    args = parser.parse_args(argv)
    if args.check_tag is not None:
        if args.change or args.commit or args.tag or args.push or args.dry_run:
            parser.error("--check-tag cannot be combined with a version change or release actions")
    elif not args.change:
        parser.error("provide patch/minor/major/X.Y.Z or --check-tag")
    if args.remote.startswith("-"):
        parser.error("--remote must be a Git remote name")
    try:
        if args.check_tag is not None:
            check_tag(Path(args.repo).expanduser().resolve(), args.check_tag)
        else:
            update(args)
        return 0
    except (ReleaseError, ExportError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
