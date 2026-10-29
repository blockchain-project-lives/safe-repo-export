"""Install this checkout into an owned virtual environment with rollback."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from .exporter import ExportError, file_lock
from .release import read_version
from .user_commands import register_commands

LOG = logging.getLogger(__name__)
MARKER = ".safe-repo-export-install.json"
TOOL = "safe-repo-export"


class InstallError(RuntimeError):
    pass


def source_fingerprint(project: Path) -> str:
    files = [project / "pyproject.toml", project / "README.md"]
    files.extend(path for path in (project / "safe_repo_export").rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(project).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def environment_python(destination: Path) -> Path:
    return destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def environment_command(destination: Path, name: str) -> Path:
    return destination / (f"Scripts/{name}.exe" if os.name == "nt" else f"bin/{name}")


def validate_install(destination: Path, version: str) -> bool:
    python = environment_python(destination)
    if not python.is_file():
        return False
    code = (
        "from importlib.metadata import distribution; from pathlib import Path; "
        "import safe_repo_export; "
        "d = distribution('safe-repo-export'); "
        f"assert d.version == {version!r} and safe_repo_export.__version__ == {version!r}; "
        "assert not d.requires; "
        "assert len(list((Path(safe_repo_export.__file__).parent / 'policies').glob('*.list'))) == 6; "
        "assert (Path(safe_repo_export.__file__).parent / 'policies/replacements.yaml').is_file(); "
        "assert (Path(safe_repo_export.__file__).parent / 'policies/stubs/example-method-body.java.txt').is_file()"
    )
    try:
        subprocess.run([str(python), "-I", "-c", code], check=True, capture_output=True)
        result = subprocess.run([str(environment_command(destination, TOOL)), "--version"],
                                check=True, capture_output=True, text=True)
        return result.stdout.strip() == version
    except (OSError, subprocess.CalledProcessError):
        return False


def remove_owned_tree(path: Path) -> None:
    if path.is_symlink():
        raise InstallError("Managed environment was replaced by a symlink; refusing cleanup")
    if not path.exists():
        return
    def clear_readonly(function, name, error):
        if not isinstance(error[1], PermissionError):
            raise error[1]
        os.chmod(name, 0o700)
        function(name)
    shutil.rmtree(path, onerror=clear_readonly)


def resolve_destination(project: Path, value: str | None) -> Path:
    project = project.resolve()
    path = Path(value).expanduser() if value else project / ".venv"
    if not path.is_absolute():
        path = project / path
    if path.is_symlink():
        raise InstallError("Virtual environment must not be a symlink")
    destination = path.resolve()
    if destination == destination.parent or destination == project or destination in project.parents:
        raise InstallError("Virtual environment cannot be a filesystem root or contain the project")
    if project in destination.parents:
        # Only dedicated hidden directories directly under the project root.
        if destination.parent != project or not destination.name.startswith(".") or destination.name in {".git", ".github"}:
            raise InstallError("Inside the project, use a hidden root directory such as .venv")
    if destination.exists():
        if not destination.is_dir():
            raise InstallError("Virtual environment destination must be a directory")
        marker = destination / MARKER
        if marker.is_symlink() or not marker.is_file():
            raise InstallError("Existing environment is not managed by this installer; choose another --venv PATH")
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise InstallError("Existing environment has invalid installation metadata") from None
        if not isinstance(state, dict) or state.get("tool") != TOOL:
            raise InstallError("Existing environment belongs to another tool")
    return destination


def install(project: Path, destination: Path, version: str, fingerprint: str, force: bool = False) -> bool:
    project = project.resolve()
    destination = resolve_destination(project, str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(destination):
        # Recheck ownership after acquiring the lock, before any mutation.
        resolve_destination(project, str(destination))
        if destination.exists():
            state = json.loads((destination / MARKER).read_text(encoding="utf-8"))
            if not force and state.get("fingerprint") == fingerprint and validate_install(destination, version):
                LOG.info("Already installed: %s %s", TOOL, version)
                return False
        if Path(sys.prefix).resolve() == destination:
            raise InstallError("Deactivate this environment and run with another Python before rebuilding it")
        transaction = Path(tempfile.mkdtemp(prefix=".safe-repo-export-install.", dir=destination.parent))
        backup = transaction / "previous-environment"
        created = False
        committed = False
        try:
            if destination.exists():
                os.replace(destination, backup)
            # Create at the final path: console scripts embed the environment's
            # absolute Python path and must remain valid after installation.
            created = True
            venv.EnvBuilder(with_pip=True).create(destination)
            subprocess.run([str(environment_python(destination)), "-m", "pip", "install",
                            "--disable-pip-version-check", "--no-deps", str(project)], check=True)
            if not validate_install(destination, version):
                raise InstallError("Installed package, bundled policies or CLI failed validation")
            (destination / MARKER).write_bytes((json.dumps({
                "tool": TOOL, "version": version, "fingerprint": fingerprint,
            }, indent=2) + "\n").encode("utf-8"))
            committed = True
        except BaseException:
            if created:
                remove_owned_tree(destination)
            if backup.exists():
                os.replace(backup, destination)
            raise
        finally:
            # Failed rollback keeps the only backup available for recovery.
            if committed or not backup.exists():
                remove_owned_tree(transaction)
        LOG.info("Installed: %s %s", TOOL, version)
        return True


def main(argv: list[str] | None = None, project: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", help="Owned virtual environment (default: project/.venv)")
    parser.add_argument("--commands-dir", help="User command launchers (default: ~/.local/bin)")
    parser.add_argument("--no-register", action="store_true", help="Install only the environment; do not register commands or PATH")
    parser.add_argument("--force", action="store_true", help="Rebuild even if the installed source is unchanged")
    parser.add_argument("--dry-run", action="store_true", help="Show the destination without changing files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    project = (project or Path.cwd()).resolve()
    try:
        if sys.version_info < (3, 10):
            raise InstallError("Python 3.10 or newer is required")
        if not shutil.which("git"):
            raise InstallError("Git is required and must be on PATH")
        _, version = read_version(project)
        destination = resolve_destination(project, args.venv)
        if args.dry_run:
            print(f"Dry run: install {TOOL} {version} into {destination}")
            return 0
        install(project, destination, version, source_fingerprint(project), args.force)
        if not args.no_register:
            commands = register_commands(destination, Path(args.commands_dir) if args.commands_dir else None)
            print(f"User commands: {commands}")
            print("Ready in new terminals: safe-repo-export --help")
            if os.name != "nt":
                import shlex
                print(f'Current terminal: export PATH={shlex.quote(str(commands))}:"$PATH"')
        print(f"Command: {environment_command(destination, TOOL)}")
        if os.name == "nt":
            print(f"Activate (PowerShell): & '{destination / 'Scripts/Activate.ps1'}'")
            print(f'Activate (CMD): "{destination / "Scripts/activate.bat"}"')
        else:
            import shlex
            print(f"Activate: source {shlex.quote(str(destination / 'bin/activate'))}")
        return 0
    except (InstallError, ExportError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        LOG.error("Local installation failed: %s", exc)
        return 2
    except KeyboardInterrupt:
        LOG.error("Installation interrupted; controlled changes rolled back")
        return 130


def interrupt_install(signum, frame):
    raise KeyboardInterrupt
