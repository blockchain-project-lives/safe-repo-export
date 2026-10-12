import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from safe_repo_export.user_commands import COMMANDS, OWNER, atomic_write, profile_update, register_commands


@unittest.skipIf(os.name == "nt", "POSIX launcher and shell-profile behavior")
class UserCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = self.root / "environment with spaces and 'quotes'"
        (self.environment / "bin").mkdir(parents=True)
        for name in COMMANDS:
            command = self.environment / "bin" / name
            command.write_bytes(b'#!/bin/sh\nprintf "%s\\n" "$@"\n')
            command.chmod(0o755)
        self.commands = self.root / "user bin"

    def test_commands_work_without_activation_and_preserve_literal_arguments(self):
        register_commands(self.environment, self.commands, configure_path=False)
        argument = "$(touch unintended-file)"
        result = subprocess.run([str(self.commands / COMMANDS[0]), argument], cwd=self.root,
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), argument)
        self.assertFalse((self.root / "unintended-file").exists())
        before = (self.commands / COMMANDS[0]).stat().st_mtime_ns
        register_commands(self.environment, self.commands, configure_path=False)
        self.assertEqual((self.commands / COMMANDS[0]).stat().st_mtime_ns, before)

    def test_existing_unmanaged_command_is_preserved(self):
        self.commands.mkdir()
        command = self.commands / COMMANDS[0]
        command.write_bytes(b"unrelated command")
        with self.assertRaises(ValueError):
            register_commands(self.environment, self.commands, configure_path=False)
        self.assertEqual(command.read_bytes(), b"unrelated command")
        self.assertFalse((self.commands / COMMANDS[1]).exists())

    def test_failed_registration_restores_previous_files(self):
        self.commands.mkdir()
        command = self.commands / COMMANDS[0]
        original = b"# " + OWNER + b"\nprevious launcher\n"
        command.write_bytes(original)
        def write(path, content, mode):
            if path.name == COMMANDS[1]:
                raise OSError("simulated write failure")
            return atomic_write(path, content, mode)
        with patch("safe_repo_export.user_commands.atomic_write", side_effect=write):
            with self.assertRaises(OSError):
                register_commands(self.environment, self.commands, configure_path=False)
        self.assertEqual(command.read_bytes(), original)
        self.assertFalse((self.commands / COMMANDS[1]).exists())

    def test_profile_configuration_preserves_existing_bytes_and_is_idempotent(self):
        home = self.root / "home"
        home.mkdir()
        profile = home / ".zshrc"
        original = b"# existing settings\r\nalias example='true'\r\n"
        profile.write_bytes(original)
        with patch.dict(os.environ, {"SHELL": "/bin/zsh", "PATH": "", "ZDOTDIR": str(home)}):
            path, content = profile_update(self.commands, home)
            self.assertEqual(path, profile.resolve())
            self.assertTrue(content.startswith(original))
            profile.write_bytes(content)
            self.assertIsNone(profile_update(self.commands, home))

    def test_already_configured_path_does_not_change_profile(self):
        with patch.dict(os.environ, {"SHELL": "/bin/zsh", "PATH": str(self.commands), "ZDOTDIR": str(self.root)}):
            self.assertIsNone(profile_update(self.commands, self.root))
        self.assertFalse((self.root / ".zshrc").exists())
