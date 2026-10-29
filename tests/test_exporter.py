import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from safe_repo_export import engine
from safe_repo_export.cli import build_parser, init_policies
from safe_repo_export.exporter import (
    ExportError, export, extract_snapshot, file_lock, publish_candidates, verify_manifest,
)


@unittest.skipUnless(shutil.which("git"), "Git is required")
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="export tests 中文 ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "source project"
        self.repo.mkdir()
        self.output = self.root / "sanitized project"
        self.git("init", "-q")
        self.git("config", "user.name", "Export test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.write("src/app.py", b'api_key = "fixture-secret"\nvalue = 1\n')
        self.write("src/app.ts", b'const apiKey = "fixture-secret";\n')
        self.write("settings.toml", b'password = "fixture-secret"\n')
        self.write("README.md", b"Project notes\n")
        self.write(".github/workflows/ci.yml", b"name: Tests\n")
        self.write(".env", b"PASSWORD=fixture-secret\n")
        self.write("node_modules/example/index.js", b"unwanted\n")
        self.write("build/generated.txt", b"unwanted\n")
        self.write("asset.dat", b"\0\1\2")
        self.write(".gitignore", b"README.md\n")
        self.commit()
        scanner = patch("safe_repo_export.exporter.run_gitleaks", return_value="not installed (built-in scan passed)")
        scanner.start()
        self.addCleanup(scanner.stop)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self):
        self.git("add", "--force", "--all")
        self.git("commit", "-q", "-m", "fixture")

    def args(self, *extras):
        return build_parser().parse_args(["--repo", str(self.repo), "--output", str(self.output), *extras])

    def test_generic_snapshot_and_metadata(self):
        original = (self.repo / "src/app.py").read_bytes()
        export(self.args())
        self.assertEqual((self.repo / "src/app.py").read_bytes(), original)
        for name in ("src/app.py", "src/app.ts", "settings.toml"):
            self.assertNotIn("fixture-secret", (self.output / name).read_text())
        for name in (".env", "node_modules", "build", "asset.dat"):
            self.assertFalse((self.output / name).exists(), name)
        self.assertTrue((self.output / ".github/workflows/ci.yml").exists())
        self.assertTrue((self.output / "README.md").exists())
        verify_manifest(self.output)
        command = ["git", "-C", str(self.output)]
        self.assertEqual(subprocess.check_output([*command, "rev-list", "--count", "HEAD"]).strip(), b"1")
        self.assertEqual(subprocess.check_output([*command, "remote"]), b"")
        self.assertEqual(subprocess.check_output([*command, "status", "--porcelain"]), b"")
        self.assertEqual(subprocess.check_output([*command, "show", "HEAD:README.md"]), b"Project notes\n")

    def test_native_git_ignores_external_global_excludes_and_attributes(self):
        export(self.args())
        ignored = self.root / "global-ignore"
        ignored.write_bytes(b"native-probe.txt\n")
        attributes = self.root / "global-attributes"
        attributes.write_bytes(b"*.py text eol=crlf\n")
        config = self.root / "global.gitconfig"
        config.write_text(
            '[core]\n    excludesFile = "' + ignored.as_posix() + '"\n' +
            '    attributesFile = "' + attributes.as_posix() + '"\n', encoding="utf-8",
        )
        (self.output / "native-probe.txt").write_bytes(b"probe\n")
        environment = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1")
        command = ["git", "-C", str(self.output)]
        status = subprocess.check_output([*command, "status", "--porcelain"], env=environment)
        self.assertIn(b"?? native-probe.txt", status)
        attribute = subprocess.check_output([*command, "check-attr", "eol", "--", "src/app.py"], env=environment)
        self.assertIn(b"eol: unspecified", attribute)

    def test_archives_checksums_and_idempotency(self):
        for kind in ("zip", "tar.gz"):
            with self.subTest(kind=kind):
                export(self.args("--archive", kind))
                archive = Path(f"{self.output}.{kind}")
                original = archive.read_bytes()
                export(self.args("--archive", kind))
                self.assertEqual(archive.read_bytes(), original)
                checksum = Path(f"{archive}.sha256").read_text().split()[0]
                self.assertEqual(checksum, hashlib.sha256(original).hexdigest())
                if kind == "zip":
                    with zipfile.ZipFile(archive) as source:
                        names = source.namelist()
                else:
                    with tarfile.open(archive) as source:
                        names = source.getnames()
                self.assertTrue(any(name.endswith("src/app.py") for name in names))
                self.assertFalse(any(".git" in Path(name).parts for name in names))
                self.assertFalse(any("pseudonym-salt" in name for name in names))

    def test_java_pem_formatting_template_exports_without_source_changes(self):
        from test_pem_format import FORMAT
        original = 'class Pem { String wrap(String privatekeyBase64) {\n' + FORMAT + '\nreturn result; } }\n'
        self.write("src/Pem.java", original.encode())
        self.git("add", "src/Pem.java")
        export(self.args("--worktree"))
        self.assertEqual((self.output / "src/Pem.java").read_text(), original)
        self.assertEqual((self.repo / "src/Pem.java").read_text(), original)

    def test_dirty_worktree_and_selected_ref(self):
        previous = self.git("rev-parse", "HEAD")
        self.write("src/app.py", b"value = 2\n")
        with self.assertRaises(ExportError):
            export(self.args())
        export(self.args("--allow-dirty"))
        self.assertIn("value = 1", (self.output / "src/app.py").read_text())
        self.commit()
        export(self.args("--ref", previous))
        self.assertIn("value = 1", (self.output / "src/app.py").read_text())

    def test_worktree_exports_disk_content_without_changing_source_index(self):
        self.write("src/app.py", b'value = 2\napi_key = "worktree-secret"\n')
        self.git("add", "src/app.py")
        self.write("src/app.py", b'value = 3\napi_key = "worktree-secret"\n')
        self.write("src/new.py", b"new_value = 4\n")
        self.git("add", "src/new.py")
        self.write("src/untracked.py", b"not_exported = True\n")
        (self.repo / "src/app.ts").unlink()
        before = self.git("status", "--porcelain")
        index = self.git("write-tree")
        head = self.git("rev-parse", "HEAD")
        export(self.args("--worktree", "--archive", "zip"))
        content = (self.output / "src/app.py").read_text()
        self.assertIn("value = 3", content)
        self.assertNotIn("worktree-secret", content)
        self.assertTrue((self.output / "src/new.py").exists())
        self.assertFalse((self.output / "src/untracked.py").exists())
        self.assertFalse((self.output / "src/app.ts").exists())
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.git("write-tree"), index)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        verify_manifest(self.output)

    def test_worktree_uses_uncommitted_policy_and_rejects_other_ref(self):
        filename = ".safe-repo-export/safe-repo-export-include.list"
        self.write(filename, b"src/app.py\n")
        export(self.args("--worktree"))
        self.assertTrue((self.output / "src/app.py").exists())
        self.assertFalse((self.output / "settings.toml").exists())
        with self.assertRaisesRegex(ExportError, "current HEAD"):
            export(self.args("--worktree", "--ref", self.git("rev-parse", "HEAD")))

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "POSIX symlink support required")
    def test_worktree_does_not_follow_replaced_directory_symlink(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "app.py").write_text("private_external_content = True\n")
        shutil.rmtree(self.repo / "src")
        (self.repo / "src").symlink_to(outside, target_is_directory=True)
        export(self.args("--worktree"))
        self.assertFalse((self.output / "src/app.py").exists())

    def prepare_java_replacement(self):
        self.write("src/Fee.java", b'package demo; class Fee { int fee(int amount) { return originalCore(amount); } int fee() { return 7; } }\n')
        self.write(".safe-repo-export/replacements.yaml", (
            'replacements:\n  - file: src/Fee.java\n    class: demo.Fee\n    method: fee\n'
            '    parameter-types:\n      - int\n    body-file: stubs/fee.java.txt\n'
        ).encode())
        self.write(".safe-repo-export/stubs/fee.java.txt", b'// PRIVATE_TEMPLATE_MARKER\nreturn 42;\n')
        self.commit()

    def test_java_replacements_use_selected_ref_hide_inputs_and_preserve_source(self):
        self.prepare_java_replacement()
        self.write(".safe-repo-export/stubs/fee.java.txt", b'return 99;\n')
        before = self.git("status", "--porcelain")
        export(self.args("--allow-dirty", "--archive", "zip"))
        result = (self.output / "src/Fee.java").read_text()
        self.assertIn("return 42", result)
        self.assertIn("return 7", result)
        self.assertNotIn("originalCore", result)
        self.assertFalse((self.output / ".safe-repo-export/replacements.yaml").exists())
        self.assertFalse((self.output / ".safe-repo-export/stubs").exists())
        report = (self.output / ".safe-repo-export/EXPORT-REPORT.md").read_text()
        self.assertIn("Java method replacements", report)
        self.assertIn("src/Fee.java", report)
        self.assertNotIn("originalCore", report)
        self.assertNotIn("PRIVATE_TEMPLATE_MARKER", report)
        self.assertIn("originalCore", (self.repo / "src/Fee.java").read_text())
        self.assertEqual(self.git("status", "--porcelain"), before)
        with zipfile.ZipFile(f"{self.output}.zip") as archive:
            self.assertFalse(any("stubs/" in name or "replacements.yaml" in name for name in archive.namelist()))
        export(self.args("--worktree", "--replace"))
        self.assertIn("return 99", (self.output / "src/Fee.java").read_text())
        verify_manifest(self.output)

    def test_failed_replacement_preserves_previous_output_and_existing_salt(self):
        self.prepare_java_replacement()
        export(self.args())
        original = (self.output / "src/Fee.java").read_bytes()
        salt = Path(f"{self.output}.pseudonym-salt").read_bytes()
        self.write("src/Fee.java", b'package demo; class Fee { int renamed(int amount) { return 99; } }\n')
        with self.assertRaisesRegex(ValueError, "match exactly"):
            export(self.args("--worktree", "--replace"))
        self.assertEqual((self.output / "src/Fee.java").read_bytes(), original)
        self.assertEqual(Path(f"{self.output}.pseudonym-salt").read_bytes(), salt)

    def test_replacement_target_excluded_or_exempt_blocks_export(self):
        self.prepare_java_replacement()
        self.write(".safe-repo-export/safe-repo-export-exclude.list", b'src/Fee.java\n')
        with self.assertRaisesRegex(ValueError, "missing or excluded"):
            export(self.args("--worktree"))
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(f"{self.output}.pseudonym-salt").exists())
        (self.repo / ".safe-repo-export/safe-repo-export-exclude.list").unlink()
        self.write(".safe-repo-export/safe-repo-export-sanitize-skip.list", b'src/Fee.java\n')
        with self.assertRaisesRegex(ExportError, "exempt"):
            export(self.args("--worktree"))

    def test_disabled_replacements_still_remove_private_inputs(self):
        self.write(".safe-repo-export/replacements.yaml", b'replacements: []\n')
        self.write(".safe-repo-export/stubs/nested/private.java.txt", b'privateBusinessDetails();\n')
        self.commit()
        export(self.args())
        self.assertFalse((self.output / ".safe-repo-export/replacements.yaml").exists())
        self.assertFalse((self.output / ".safe-repo-export/stubs").exists())

    def test_stub_contents_are_redacted_after_replacement(self):
        self.prepare_java_replacement()
        self.write(".safe-repo-export/stubs/fee.java.txt", b'String apiKey = "fixture-template-secret";\nreturn 42;\n')
        export(self.args("--worktree"))
        content = (self.output / "src/Fee.java").read_text()
        self.assertNotIn("fixture-template-secret", content)
        self.assertIn("REDACTED_SECRET", content)

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "POSIX symlink support required")
    def test_replacement_template_symlink_rejected_in_both_modes(self):
        self.prepare_java_replacement()
        target = self.repo / ".safe-repo-export/stubs/fee.java.txt"
        target.unlink()
        target.symlink_to(self.repo / "README.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            export(self.args("--worktree"))
        self.commit()
        with self.assertRaisesRegex(ExportError, "regular files"):
            export(self.args())

    def test_replace_required_and_preserves_previous_on_conflict(self):
        export(self.args("--archive", "zip"))
        old = (self.output / "src/app.py").read_bytes()
        old_archive = Path(f"{self.output}.zip").read_bytes()
        self.write("src/app.py", b"value = 3\n")
        self.commit()
        with self.assertRaises(ExportError):
            export(self.args("--archive", "zip"))
        self.assertEqual((self.output / "src/app.py").read_bytes(), old)
        self.assertEqual(Path(f"{self.output}.zip").read_bytes(), old_archive)
        export(self.args("--archive", "zip", "--replace"))
        self.assertEqual((self.output / "src/app.py").read_bytes(), b"value = 3\n")

    def test_archive_conflict_is_checked_before_output_changes(self):
        archive = Path(f"{self.output}.zip")
        archive.write_bytes(b"existing archive")
        with self.assertRaises(ExportError):
            export(self.args("--archive", "zip"))
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(f"{self.output}.pseudonym-salt").exists())
        self.assertEqual(archive.read_bytes(), b"existing archive")

    def test_policy_precedence_and_uncommitted_policy(self):
        self.write(".safe-repo-export/safe-repo-export-include.list", b"README.md\n")
        self.commit()
        self.write(".safe-repo-export/safe-repo-export-include.list", b"src/**\n")
        export(self.args("--allow-dirty"))
        self.assertTrue((self.output / "README.md").exists())
        self.assertFalse((self.output / "src").exists())
        explicit = self.root / "custom.list"
        explicit.write_bytes(b"src/**\n")
        export(self.args("--allow-dirty", "--replace", "--include-list", str(explicit)))
        self.assertFalse((self.output / "README.md").exists())
        self.assertTrue((self.output / "src/app.py").exists())

    def test_empty_include_policy_exports_empty_snapshot(self):
        explicit = self.root / "empty.list"
        explicit.write_bytes(b"")
        export(self.args("--include-list", str(explicit)))
        self.assertFalse((self.output / "src").exists())
        verify_manifest(self.output)

    def test_rejects_output_inside_or_containing_source(self):
        for output in (self.repo / "export", self.root, self.repo):
            args = self.args()
            args.output = str(output)
            with self.assertRaises(ExportError):
                export(args)
        self.assertTrue((self.repo / "src/app.py").exists())

    def test_rejects_salt_inside_source_or_output(self):
        for salt in (self.repo / "salt", self.output / "salt", self.output):
            with self.assertRaises(ExportError):
                export(self.args("--salt-file", str(salt)))
        self.assertFalse(self.output.exists())

    def test_failure_cleans_new_salt_and_staging(self):
        self.write("policy.list", ("ghp_" + "A9bC2d" * 6 + "\n").encode())
        self.commit()
        with self.assertRaises(ExportError):
            export(self.args())
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(f"{self.output}.pseudonym-salt").exists())
        self.assertFalse(any(path.is_dir() for path in self.root.glob(".safe-repo-export.*")))

    def test_committed_crlf_source_bytes_are_preserved(self):
        self.write("src/normal.py", b"value = 42\r\nother = 10\r\n")
        self.commit()
        export(self.args())
        self.assertEqual((self.output / "src/normal.py").read_bytes(), b"value = 42\r\nother = 10\r\n")

    def test_executable_git_mode_is_preserved_in_snapshot_and_archives(self):
        self.write("run.py", b"print(42)\n")
        if os.name != "nt":
            (self.repo / "run.py").chmod(0o755)
        self.git("add", "run.py")
        self.git("update-index", "--chmod=+x", "--", "run.py")
        self.git("commit", "-q", "-m", "executable fixture")
        for kind in ("zip", "tar.gz"):
            export(self.args("--archive", kind))
            mode = subprocess.check_output(["git", "-C", str(self.output), "ls-tree", "HEAD", "--", "run.py"])
            self.assertTrue(mode.startswith(b"100755 "))
            name = f"{self.output.name}/run.py"
            if kind == "zip":
                with zipfile.ZipFile(f"{self.output}.{kind}") as archive:
                    self.assertEqual((archive.getinfo(name).external_attr >> 16) & 0o777, 0o755)
            else:
                with tarfile.open(f"{self.output}.{kind}") as archive:
                    self.assertEqual(archive.getmember(name).mode, 0o755)

    def test_identical_files_with_existing_remote_require_replacement(self):
        export(self.args())
        subprocess.run(["git", "-C", str(self.output), "remote", "add", "origin", str(self.repo)], check=True)
        with self.assertRaises(ExportError):
            export(self.args())
        export(self.args("--replace"))
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.output), "remote"]), b"")


class TransactionTests(unittest.TestCase):
    def test_kernel_lock_rejects_concurrent_lock_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "output"
            with file_lock(path):
                with self.assertRaises(ExportError):
                    with file_lock(path):
                        self.fail("Lock was not exclusive")
            with file_lock(path):
                pass

    def test_rolls_back_all_destinations_after_move_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = root / "transaction"
            transaction.mkdir()
            pairs = []
            for name in ("output", "archive", "checksum"):
                candidate = transaction / name
                candidate.write_bytes(b"new")
                target = root / name
                target.write_bytes(b"old")
                pairs.append((candidate, target))
            original_replace = os.replace
            def move(source, target):
                if Path(source) == transaction / "checksum":
                    raise OSError("simulated failure")
                original_replace(source, target)
            with patch("safe_repo_export.exporter.os.replace", side_effect=move):
                with self.assertRaises(OSError):
                    publish_candidates(pairs, transaction, True)
            for _, target in pairs:
                self.assertEqual(target.read_bytes(), b"old")

    def test_extraction_rejects_traversal_and_omits_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            archive = root / "snapshot.tar"
            with tarfile.open(archive, "w") as target:
                link = tarfile.TarInfo("link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../secret"
                target.addfile(link)
            self.assertEqual(extract_snapshot(archive, output), 1)
            self.assertFalse((output / "link").exists())
            with tarfile.open(archive, "w") as target:
                item = tarfile.TarInfo("../escaped")
                item.size = 3
                target.addfile(item, io.BytesIO(b"bad"))
            with self.assertRaises(ExportError):
                extract_snapshot(archive, output)
            self.assertFalse((root / "escaped").exists())

    def test_hidden_paths_and_root_globstar(self):
        self.assertTrue(engine.match_pattern(".github/workflows/ci.yml", ".github/**"))
        self.assertFalse(engine.match_pattern("github/workflows/ci.yml", ".github/**"))
        self.assertTrue(engine.match_pattern(".env", "**/.env"))
        self.assertTrue(engine.match_pattern("build/a.txt", "**/build/**"))

    def test_policy_initialization_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "policies"
            init_policies(["--directory", str(directory)])
            path = directory / "safe-repo-export-include.list"
            path.write_bytes(b"src/**\r\n")
            init_policies(["--directory", str(directory)])
            self.assertEqual(path.read_bytes(), b"src/**\r\n")
            self.assertEqual(len(list(directory.glob("*.list"))), 6)
            config = directory / "replacements.yaml"
            stub = directory / "stubs/example-method-body.java.txt"
            from safe_repo_export.replacements import parse_config
            self.assertEqual(parse_config(config.read_text()), [])
            self.assertIn("Export-only mock", stub.read_text())
            self.assertFalse((directory / "stubs/example-method-body.java").exists())
            config.write_bytes(b"replacements: []\r\n# user settings\r\n")
            stub.write_bytes(b"// user-owned template\r\nreturn 7;\r\n")
            init_policies(["--directory", str(directory)])
            self.assertEqual(config.read_bytes(), b"replacements: []\r\n# user settings\r\n")
            self.assertEqual(stub.read_bytes(), b"// user-owned template\r\nreturn 7;\r\n")


    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "POSIX symlink support required")
    def test_init_does_not_write_through_symlinked_stubs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "policies"
            outside = Path(temporary) / "outside"
            directory.mkdir()
            outside.mkdir()
            (directory / "stubs").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ExportError, "symlink"):
                init_policies(["--directory", str(directory)])
            self.assertEqual(list(outside.iterdir()), [])


class GitleaksTests(unittest.TestCase):
    def test_required_scan_and_strict_error_handling(self):
        from safe_repo_export.exporter import run_gitleaks
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(require_gitleaks=True, gitleaks_strict=False)
            with patch("safe_repo_export.exporter.shutil.which", return_value=None):
                with self.assertRaises(ExportError):
                    run_gitleaks(args, root, root, {})
            args.require_gitleaks = False
            with patch("safe_repo_export.exporter.shutil.which", return_value="gitleaks"), patch(
                "safe_repo_export.exporter.subprocess.run", return_value=subprocess.CompletedProcess([], 2)
            ):
                self.assertIn("scan error", run_gitleaks(args, root, root, {}))
                args.gitleaks_strict = True
                with self.assertRaises(ExportError):
                    run_gitleaks(args, root, root, {})
