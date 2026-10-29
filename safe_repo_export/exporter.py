"""Export orchestration implemented with Python's standard library.

Git and optional Gitleaks are invoked directly, never through a shell.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from . import engine, replacements

LOG = logging.getLogger(__name__)
POLICIES = {
    "include_list": "safe-repo-export-include.list",
    "exclude_list": "safe-repo-export-exclude.list",
    "skip_list": "safe-repo-export-sanitize-skip.list",
    "redact_keys": "safe-repo-export-redact-keys.list",
    "public_hosts": "safe-repo-export-public-hosts.list",
    "gitleaks_ignore": "safe-repo-export-gitleaks-ignore.list",
}
DEFAULT_POLICIES = Path(__file__).parent / "policies"


class ExportError(RuntimeError):
    """A safe, user-facing export failure."""


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    environment = dict(os.environ if env is None else env)
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1")
    process = subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=environment, check=False,
    )
    if process.returncode:
        # Do not echo Git output: source paths or hooks may contain secrets.
        raise ExportError(f"Git {args[0]} failed (exit {process.returncode})")
    return process.stdout


def within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def resolve_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ExportError(f"{label} must not be a symlink: {path}")
    return path.resolve()


@contextlib.contextmanager
def file_lock(target: Path):
    """Kernel locks release on process exit, including crashes, on all three OSes."""
    key = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()[:20]
    path = target.parent / f".safe-repo-export.{key}.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise ExportError(f"Lock file must not be a symlink: {path}")
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ExportError("Lock path is not a regular file")
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"\0")
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ExportError(f"Another export is using: {target}") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    # Keep the lock inode: unlinking it would let concurrent processes lock
    # different files for the same target.


def resolve_policies(args, repo: Path, commit: str, transaction: Path) -> dict[str, Path]:
    selected = {}
    for option, filename in POLICIES.items():
        explicit = getattr(args, option)
        if explicit is not None:
            path = resolve_path(explicit, filename)
        elif args.worktree:
            path = repo / ".safe-repo-export" / filename
            if path.is_symlink() or path.parent.is_symlink():
                raise ExportError(f"Repository policy must be a regular file: {filename}")
            if path.exists():
                if not path.is_file():
                    raise ExportError(f"Policy is not a regular file: {filename}")
                content = path.read_bytes()
                path = transaction / filename
                path.write_bytes(content)
            else:
                path = DEFAULT_POLICIES / filename
        else:
            entry = git(repo, "ls-tree", commit, "--", f".safe-repo-export/{filename}")
            if entry:
                if entry.split(b" ", 1)[0] not in {b"100644", b"100755"}:
                    raise ExportError(f"Repository policy must be a regular file: {filename}")
                path = transaction / filename
                path.write_bytes(git(repo, "show", f"{commit}:.safe-repo-export/{filename}"))
                LOG.info("Using committed repository policy: %s", filename)
            else:
                path = DEFAULT_POLICIES / filename
        if not path.is_file():
            raise ExportError(f"Policy is not a regular file: {path}")
        selected[option] = path
    return selected


def copy_worktree(repo: Path, root: Path, executables: set[str]) -> int:
    """Copy indexed paths from disk without modifying the index or following links."""
    skipped_links = 0
    for entry in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, _, stage = metadata.split()
        if stage != b"0":
            raise ExportError("Resolve merge conflicts before using --worktree")
        name = PurePosixPath(os.fsdecode(raw_name))
        if (name.is_absolute() or ".." in name.parts or ".git" in name.parts
                or any(char in str(name) for char in "\\:\n\r")):
            raise ExportError("Worktree contains an unsafe or non-portable path")
        if mode == b"160000":
            continue  # Do not descend into submodules.
        if mode == b"120000":
            skipped_links += 1
            continue
        source = repo.joinpath(*name.parts)
        if any(parent.is_symlink() for parent in [source, *source.parents] if parent != repo):
            skipped_links += 1
            continue
        try:
            info = source.stat()
        except FileNotFoundError:
            continue  # Tracked file deleted in the working directory.
        if not stat.S_ISREG(info.st_mode):
            raise ExportError("Worktree contains a tracked path that is not a regular file")
        target = root.joinpath(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        executable = mode == b"100755"
        target.chmod(0o755 if executable else 0o644)
        if executable:
            executables.add(name.as_posix())
    return skipped_links


def extract_snapshot(archive: Path, root: Path, executables: set[str] | None = None) -> int:
    """Read only regular files; never follow links or execute archive content."""
    skipped_links = 0
    with tarfile.open(archive, "r:") as source:
        for member in source:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or ".git" in name.parts
                    or "\\" in member.name or ":" in member.name
                    or "\n" in member.name or "\r" in member.name):
                raise ExportError("Snapshot contains an unsafe or non-portable path")
            target = root.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.issym() or member.islnk():
                skipped_links += 1
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content, target.open("xb") as output:
                    shutil.copyfileobj(content, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
                if executables is not None and member.mode & 0o111:
                    executables.add(name.as_posix())
            else:
                raise ExportError("Snapshot contains an unsupported file type")
    return skipped_links


def run_gitleaks(args, root: Path, transaction: Path, policies: dict[str, Path]) -> str:
    executable = shutil.which("gitleaks")
    if not executable:
        if args.require_gitleaks or args.gitleaks_strict:
            raise ExportError("Gitleaks is required but not installed")
        return "not installed (built-in scan passed)"
    report = transaction / "gitleaks.json"
    process = subprocess.run([
        executable, "dir", str(root), "--redact=100", "--report-format", "json",
        "--report-path", str(report), "--exit-code", "7",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if process.returncode not in {0, 7}:
        if args.gitleaks_strict:
            raise ExportError(f"Gitleaks scan failed (exit {process.returncode})")
        LOG.warning("Gitleaks scan failed (exit %s)", process.returncode)
        return f"scan error {process.returncode} (non-blocking)"
    if process.returncode == 0 and not report.exists():
        report.write_bytes(b"[]\n")
    try:
        result = engine.command_summarize_gitleaks(argparse.Namespace(
            input=str(report), root=str(root), skip_list=str(policies["skip_list"]),
            ignore_state=str(transaction / "gitleaks-ignore-state.json"),
            summary=str(transaction / "gitleaks-summary.json"),
        ))
    except (SystemExit, ValueError, OSError, TypeError, KeyError):
        if args.gitleaks_strict:
            raise ExportError("Gitleaks report is invalid") from None
        LOG.warning("Gitleaks report is invalid")
        return "report error (non-blocking)"
    if result:
        if args.gitleaks_strict:
            raise ExportError("Gitleaks findings blocked export in strict mode")
        LOG.warning("Gitleaks findings remain; see GITLEAKS-REPORT.json")
        return "warnings (non-blocking; see GITLEAKS-REPORT.json)"
    return "passed (configured ignores applied)"


def verify_manifest(root: Path) -> None:
    expected = "\n".join(engine.manifest_lines(root)) + "\n"
    if (root / ".safe-repo-export/MANIFEST.sha256").read_bytes() != expected.encode("utf-8"):
        raise ExportError("Export manifest verification failed")


def validate_snapshot(root: Path) -> None:
    if not (root / ".git").is_dir() or (root / ".git").is_symlink():
        raise ExportError("Output must contain a standalone Git snapshot repository")
    if (git(root, "status", "--porcelain") or git(root, "remote")
            or git(root, "rev-list", "--count", "HEAD").strip() != b"1"):
        raise ExportError("Snapshot must be clean, contain one commit and have no remotes")
    verify_manifest(root)


def initialize_snapshot(root: Path, epoch: int, executables: set[str]) -> None:
    template = root.parent / "empty-git-template"
    template.mkdir()
    git(root, "init", "-q", f"--template={template}")
    git(root, "config", "user.name", "Sanitized Export")
    git(root, "config", "user.email", "export@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    # Disable global hooks, excludes and attributes that could mutate the export.
    empty_hooks = root / ".git/export-empty-hooks"
    empty_hooks.mkdir()
    git(root, "config", "core.hooksPath", str(empty_hooks))
    # Empty values disable global files without persisting platform-specific
    # null-device names (Git for Windows rejects nul as an exclude file).
    git(root, "config", "core.excludesFile", "")
    git(root, "config", "core.attributesFile", "")
    git(root, "add", "--force", "--all")
    for name in sorted(executables):
        if (root / name).is_file():
            # Windows chmod cannot represent POSIX executable bits; retain the
            # original Git mode in the snapshot index instead.
            git(root, "update-index", "--chmod=+x", "--", name)
    env = dict(os.environ, GIT_AUTHOR_DATE=f"@{epoch} +0000", GIT_COMMITTER_DATE=f"@{epoch} +0000")
    git(root, "commit", "-q", "--allow-empty", "-m", "Sanitized project snapshot", env=env)
    # Remove the temporary absolute path from the generated repository config.
    git(root, "config", "--unset", "core.hooksPath")
    validate_snapshot(root)


def tree_fingerprint(root: Path) -> dict[str, tuple[str, int]]:
    result = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise ExportError(f"Existing output contains a symlink: {path}")
        if path.is_file():
            mode = int(bool(path.stat().st_mode & 0o111)) if os.name != "nt" else 0
            result[path.relative_to(root).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(), mode)
        elif not path.is_dir():
            raise ExportError("Output contains an unsupported file type")
    return result


def create_archive(root: Path, destination: Path, name: str, kind: str, epoch: int, executables: set[str]) -> None:
    """Deterministic archives of the sanitized snapshot, excluding Git internals."""
    paths = [root, *sorted(p for p in root.rglob("*") if ".git" not in p.relative_to(root).parts)]
    if kind == "zip":
        import time
        timestamp = time.gmtime(max(315532800, min(epoch, 4354819198)))[:6]
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                relative = PurePosixPath(name) / path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(str(relative).rstrip("/") + ("/" if path.is_dir() else ""), timestamp)
                info.create_system = 3
                mode = (stat.S_IFDIR | 0o755) if path.is_dir() else (stat.S_IFREG | (0o755 if path.relative_to(root).as_posix() in executables else 0o644))
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, b"" if path.is_dir() else path.read_bytes())
    else:
        with destination.open("wb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in paths:
                    info = archive.gettarinfo(str(path), str(PurePosixPath(name) / path.relative_to(root).as_posix()))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = epoch
                    info.mode = 0o755 if path.is_dir() or path.relative_to(root).as_posix() in executables else 0o644
                    if path.is_file():
                        with path.open("rb") as content:
                            archive.addfile(info, content)
                    else:
                        archive.addfile(info)


def publish_candidates(pairs: list[tuple[Path, Path]], transaction: Path, replace: bool) -> bool:
    """Validate every destination before writing; restore all backups on failure."""
    pending = []
    for candidate, target in pairs:
        if target.is_symlink():
            raise ExportError(f"Destination must not be a symlink: {target}")
        if target.exists():
            if target.is_dir() != candidate.is_dir() or (not target.is_dir() and not target.is_file()):
                raise ExportError(f"Destination has the wrong file type: {target}")
            same = (tree_fingerprint(target) == tree_fingerprint(candidate) if candidate.is_dir()
                    else target.read_bytes() == candidate.read_bytes())
            if same and candidate.is_dir():
                try:
                    validate_snapshot(target)
                except (ExportError, OSError):
                    same = False
            if same:
                continue
            if not replace:
                raise ExportError(f"Destination exists and differs; use --replace: {target}")
        pending.append((candidate, target))
    installed = []
    backups = []
    try:
        for index, (candidate, target) in enumerate(pending):
            if target.exists():
                backup = transaction / f"previous-{index}"
                os.replace(target, backup)
                backups.append((backup, target))
            os.replace(candidate, target)
            installed.append(target)
    except BaseException:
        for target in reversed(installed):
            if target.is_dir():
                def remove_readonly(function, name, error):
                    if not isinstance(error[1], PermissionError):
                        raise error[1]
                    os.chmod(name, 0o700)
                    function(name)
                shutil.rmtree(target, onerror=remove_readonly)
            else:
                target.unlink()
        for backup, target in reversed(backups):
            os.replace(backup, target)
        raise
    return bool(pending)


def export(args) -> Path:
    if not shutil.which("git"):
        raise ExportError("Git is required and must be on PATH")
    repo = Path(os.fsdecode(git(Path(args.repo), "rev-parse", "--show-toplevel")).strip()).resolve()
    output = resolve_path(args.output, "Output")
    if within(output, repo) or within(repo, output) or output == output.parent:
        raise ExportError("Output must be outside the source repository and cannot contain it")
    if output.exists() and not output.is_dir():
        raise ExportError("Output must be a directory")
    if args.worktree and args.ref != "HEAD":
        raise ExportError("--worktree uses current HEAD and cannot be combined with another --ref")
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", f"{args.ref}^{{commit}}").decode().strip()
    epoch = int(git(repo, "show", "-s", "--format=%ct", commit))
    if not args.worktree and not args.allow_dirty and git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ExportError("Tracked changes exist; use --worktree to include edits, or --allow-dirty to export only committed content")
    salt = resolve_path(args.salt_file or f"{output}.pseudonym-salt", "Salt file")
    targets = [output]
    if args.archive != "none":
        archive_target = Path(f"{output}.{args.archive}")
        checksum_target = Path(f"{archive_target}.sha256")
        targets.extend([archive_target, checksum_target])
    if within(salt, repo) or any(within(salt, target) for target in targets):
        raise ExportError("Salt file must be outside the source, output and archive destinations")
    if salt.exists() and not salt.is_file():
        raise ExportError("Salt must be a regular file")
    output.parent.mkdir(parents=True, exist_ok=True)
    salt.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as locks:
        for target in sorted(set([*targets, salt])):
            locks.enter_context(file_lock(target))
        salt_created = not salt.exists()
        destinations_committed = False
        try:
            with tempfile.TemporaryDirectory(prefix=".safe-repo-export.", dir=output.parent) as temporary:
                transaction = Path(temporary)
                candidate = transaction / "candidate"
                candidate.mkdir()
                policies = resolve_policies(args, repo, commit, transaction)
                def read_replacement_input(name: str) -> bytes | None:
                    if args.worktree:
                        return replacements.read_worktree(repo, name)
                    for parent in PurePosixPath(name).parents:
                        if str(parent) == ".":
                            continue
                        ancestor = git(repo, "ls-tree", commit, "--", parent.as_posix())
                        if ancestor and ancestor.split(b" ", 1)[0] != b"040000":
                            raise ExportError("Replacement input parents must be ordinary directories")
                    entry = git(repo, "ls-tree", commit, "--", name)
                    if not entry:
                        return None
                    if entry.split(b" ", 1)[0] not in {b"100644", b"100755"}:
                        raise ExportError("Replacement inputs must be regular files")
                    return git(repo, "show", f"{commit}:{name}")
                replacement_rules = replacements.load_rules(read_replacement_input)
                for rule in replacement_rules:
                    if engine.matches_any(rule.file, engine.read_list(policies["skip_list"])):
                        raise ExportError("Replacement targets cannot be exempt from redaction and scanning")
                engine.command_generate_salt(argparse.Namespace(output=str(salt)))
                executables: set[str] = set()
                if args.worktree:
                    skipped_links = copy_worktree(repo, candidate, executables)
                else:
                    snapshot = transaction / "snapshot.tar"
                    git(repo, "archive", "--format=tar", f"--output={snapshot}", commit)
                    skipped_links = extract_snapshot(snapshot, candidate, executables)
                    snapshot.unlink()
                replacements.remove_private_inputs(candidate)
                replacement_records = []
                def replace_methods(root: Path) -> int:
                    replacement_records.extend(replacements.apply_rules(root, replacement_rules))
                    return len(replacement_records)
                state = transaction / "sanitize-state.json"
                LOG.info("Filtering and sanitizing %s", "working tree" if args.worktree else "selected commit")
                result = engine.command_sanitize(argparse.Namespace(
                    root=str(candidate), include=str(policies["include_list"]), exclude=str(policies["exclude_list"]),
                    skip_list=str(policies["skip_list"]), redact_keys=str(policies["redact_keys"]),
                    public_hosts=str(policies["public_hosts"]), salt_file=str(salt), state=str(state),
                    gitleaks_ignore=str(policies["gitleaks_ignore"]),
                    ignore_state=str(transaction / "gitleaks-ignore-state.json"),
                    before_redaction=replace_methods,
                ))
                if result:
                    raise ExportError("Built-in residual-secret scan blocked export")
                if skipped_links or replacement_records:
                    data = json.loads(state.read_text(encoding="utf-8"))
                    if skipped_links:
                        data["counts"]["unsafe_symlink_removed"] = skipped_links
                    data["replacements"] = replacement_records
                    state.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                status = run_gitleaks(args, candidate, transaction, policies)
                engine.command_finalize(argparse.Namespace(
                    root=str(candidate), state=str(state), gitleaks_status=status,
                    gitleaks_summary=str(transaction / "gitleaks-summary.json"),
                ))
                verify_manifest(candidate)
                initialize_snapshot(candidate, epoch, executables)
                pairs = [(candidate, output)]
                if args.archive != "none":
                    archive = transaction / f"archive.{args.archive}"
                    create_archive(candidate, archive, output.name, args.archive, epoch, executables)
                    checksum = transaction / "archive.sha256"
                    checksum.write_bytes(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive_target.name}\n".encode("utf-8"))
                    pairs.extend([(archive, archive_target), (checksum, checksum_target)])
                changed = publish_candidates(pairs, transaction, args.replace)
                destinations_committed = True
        except BaseException:
            if salt_created and not destinations_committed and salt.is_file():
                salt.unlink()
            raise
    LOG.info("Export %s: %s", "completed" if changed else "unchanged", output)
    LOG.info("Keep the salt private: %s", salt)
    return output
