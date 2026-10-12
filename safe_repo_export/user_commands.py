"""Expose installed CLI commands through user-owned launchers and shell PATH."""
from __future__ import annotations

import os
import shlex
import sys
import tempfile
from pathlib import Path

from .exporter import file_lock

COMMANDS = ("safe-repo-export", "safe-repo-export-version")
OWNER = b"Managed by safe-repo-export installer"
BEGIN = b"# BEGIN MANAGED BLOCK: safe-repo-export-path"
END = b"# END MANAGED BLOCK: safe-repo-export-path"


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".safe-repo-export-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def profile_update(directory: Path, home: Path) -> tuple[Path, bytes] | None:
    # An already-configured user bin needs no startup-file changes.
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "zsh":
        profile = Path(os.environ.get("ZDOTDIR", str(home))) / ".zshrc"
    elif shell == "bash":
        profile = home / (".bash_profile" if sys.platform == "darwin" else ".bashrc")
    elif shell == "fish":
        profile = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "fish/conf.d/safe-repo-export.fish"
    else:
        profile = home / ".profile"
    profile = profile.expanduser().resolve()
    original = profile.read_bytes() if profile.exists() else b""
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError("Shell profile has malformed safe-repo-export PATH markers")
    if not original.count(BEGIN) and str(directory) in os.environ.get("PATH", "").split(os.pathsep):
        return None
    path_value = shlex.quote(str(directory))
    line = (f"set -gx PATH {path_value} $PATH" if shell == "fish" else f"export PATH={path_value}:\"$PATH\"")
    block = BEGIN + b"\n" + line.encode("utf-8") + b"\n" + END
    if BEGIN in original:
        start = original.index(BEGIN)
        end = original.index(END, start) + len(END)
        content = original[:start] + block + original[end:]
    else:
        content = original + (b"\n" if original and not original.endswith(b"\n") else b"") + block + b"\n"
    return (profile, content) if content != original else None


def windows_path(directory: Path) -> None:
    import ctypes
    import winreg
    from ctypes import wintypes
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        paths = [entry for entry in current.split(";") if entry]
        if os.path.normcase(str(directory)) not in [os.path.normcase(os.path.expandvars(entry)) for entry in paths]:
            winreg.SetValueEx(key, "Path", 0, kind, ";".join([*paths, str(directory)]))
    # Notify Explorer so newly launched terminals inherit the updated user PATH.
    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


def register_commands(destination: Path, directory: Path | None = None, *, configure_path: bool = True) -> Path:
    home = Path.home()
    directory = (directory or home / ".local/bin").expanduser().absolute()
    if directory.is_symlink():
        raise ValueError("User commands directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    changes = []
    with file_lock(directory / "safe-repo-export-user-commands"):
        for name in COMMANDS:
            target = destination / (f"Scripts/{name}.exe" if os.name == "nt" else f"bin/{name}")
            if not target.is_file():
                raise ValueError(f"Installed command is missing: {name}")
            path = directory / (name + ".cmd" if os.name == "nt" else name)
            if path.is_symlink() or (path.exists() and (not path.is_file() or OWNER not in path.read_bytes())):
                raise ValueError(f"An unmanaged command already exists: {path}; use --no-register or another --commands-dir")
            if os.name == "nt":
                quoted = str(target).replace("%", "%%")
                content = f'@echo off\r\nREM {OWNER.decode()}\r\nsetlocal DisableDelayedExpansion\r\n"{quoted}" %*\r\n'.encode("utf-8")
            else:
                content = f'#!/bin/sh\n# {OWNER.decode()}\nexec {shlex.quote(str(target))} "$@"\n'.encode("utf-8")
            if not path.exists() or path.read_bytes() != content:
                changes.append((path, content, 0o755))
        if configure_path and os.name != "nt":
            update = profile_update(directory, home)
            if update:
                path, content = update
                mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
                changes.append((path, content, mode))
        backups = []
        try:
            for path, content, mode in changes:
                backups.append((path, path.read_bytes() if path.exists() else None,
                                path.stat().st_mode & 0o777 if path.exists() else mode))
                atomic_write(path, content, mode)
            if configure_path and os.name == "nt":
                windows_path(directory)
        except BaseException:
            for path, content, mode in reversed(backups):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, content, mode)
            raise
    return directory
