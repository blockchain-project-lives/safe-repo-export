import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from safe_repo_export.installer import (
    MARKER, TOOL, InstallError, install, resolve_destination,
)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="safe-repo-install-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.destination = self.project / ".venv"

    def owned_environment(self):
        self.destination.mkdir()
        (self.destination / MARKER).write_text(json.dumps({"tool": TOOL, "fingerprint": "old"}))
        (self.destination / "previous.txt").write_bytes(b"previous environment")

    def test_unmanaged_environment_is_preserved(self):
        self.destination.mkdir()
        (self.destination / "user.txt").write_bytes(b"user data")
        with self.assertRaises(InstallError):
            resolve_destination(self.project, str(self.destination))
        self.assertEqual((self.destination / "user.txt").read_bytes(), b"user data")

    def test_rejects_source_and_parent_destinations(self):
        for path in (self.project, self.project.parent, self.project / "safe_repo_export", self.project / ".git"):
            with self.subTest(path=path), self.assertRaises(InstallError):
                resolve_destination(self.project, str(path))

    def test_repeated_unchanged_install_does_not_reinstall(self):
        self.owned_environment()
        marker = self.destination / MARKER
        marker.write_text(json.dumps({"tool": TOOL, "fingerprint": "same"}))
        original = marker.read_bytes()
        with patch("safe_repo_export.installer.validate_install", return_value=True), patch(
            "safe_repo_export.installer.venv.EnvBuilder"
        ) as builder:
            self.assertFalse(install(self.project, self.destination, "0.1.0", "same"))
            builder.assert_not_called()
        self.assertEqual(marker.read_bytes(), original)
        self.assertEqual((self.destination / "previous.txt").read_bytes(), b"previous environment")

    def test_failed_upgrade_restores_previous_environment(self):
        self.owned_environment()
        marker = (self.destination / MARKER).read_bytes()
        def create(destination):
            destination.mkdir()
            (destination / "partial.txt").write_bytes(b"incomplete")
        with patch("safe_repo_export.installer.venv.EnvBuilder") as builder, patch(
            "safe_repo_export.installer.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["pip"])
        ):
            builder.return_value.create.side_effect = create
            with self.assertRaises(subprocess.CalledProcessError):
                install(self.project, self.destination, "0.1.1", "new")
        self.assertEqual((self.destination / MARKER).read_bytes(), marker)
        self.assertEqual((self.destination / "previous.txt").read_bytes(), b"previous environment")
        self.assertFalse((self.destination / "partial.txt").exists())
        self.assertFalse(any(path.is_dir() for path in self.project.glob(".safe-repo-export-install.*")))

    def test_failed_first_install_removes_only_created_environment(self):
        def create(destination):
            destination.mkdir()
            raise OSError("venv creation failed")
        with patch("safe_repo_export.installer.venv.EnvBuilder") as builder:
            builder.return_value.create.side_effect = create
            with self.assertRaises(OSError):
                install(self.project, self.destination, "0.1.0", "new")
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.project.exists())


@unittest.skipUnless(os.name != "nt" and shutil.which("bash") and shutil.which("git"), "POSIX Bash wrappers")
class ShellEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="safe-repo-shell-tests-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(__file__).resolve().parents[1]
        self.project = Path(self.temporary.name) / "project with spaces"
        self.project.mkdir()
        for name in ("install.sh", "install.py", "bump_version.sh", "commit_and_tag.sh", "pyproject.toml"):
            shutil.copy2(root / name, self.project / name)
        (self.project / "scripts").mkdir()
        shutil.copy2(root / "scripts/bump_version.py", self.project / "scripts/bump_version.py")
        shutil.copytree(root / "safe_repo_export", self.project / "safe_repo_export", ignore=shutil.ignore_patterns("__pycache__"))
        (self.project / ".gitignore").write_bytes(b"__pycache__/\n*.pyc\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Wrapper test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.project), *args], stderr=subprocess.PIPE).decode().strip()

    def run_wrapper(self, name, *args, env=None):
        return subprocess.run(["bash", str(self.project / name), *args],
                              cwd=self.project.parent, capture_output=True, text=True, env=env)

    def test_version_wrapper_works_outside_project_and_preserves_dry_run(self):
        version = self.project / "safe_repo_export/_version.py"
        original = version.read_bytes()
        result = self.run_wrapper("bump_version.sh", "patch", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertEqual(version.read_bytes(), original)

    def test_install_wrapper_uses_its_own_project_directory(self):
        result = self.run_wrapper("install.sh", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.project / ".venv"), result.stdout)
        self.assertFalse((self.project / ".venv").exists())

    def test_explicit_missing_python_fails_before_mutation(self):
        environment = dict(os.environ, SAFE_REPO_EXPORT_PYTHON="/missing/python with spaces")
        result = self.run_wrapper("install.sh", "--dry-run", env=environment)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Python 3.10", result.stderr)
        self.assertFalse((self.project / ".venv").exists())

    def test_restored_commit_and_tag_entry_forwards_literal_message(self):
        from safe_repo_export.release import read_version, next_version
        _, current = read_version(self.project)
        version = next_version(current, "patch")
        message = "Release with spaces and $(touch unexpected-file)"
        result = self.run_wrapper("commit_and_tag.sh", "v" + version, message)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("tag", "--list"), "v" + version)
        self.assertEqual(self.git("log", "-1", "--format=%s"), message)
        self.assertFalse((self.project / "unexpected-file").exists())
        self.assertFalse((self.project.parent / "unexpected-file").exists())
