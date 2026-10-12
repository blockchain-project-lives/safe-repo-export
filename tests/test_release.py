import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from safe_repo_export.release import VERSION_PATH, check_tag, main, next_version, ReleaseError


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "project"
        (self.repo / VERSION_PATH.parent).mkdir(parents=True)
        (self.repo / "pyproject.toml").write_bytes(b"[project]\nname = 'fixture'\n")
        self.path = self.repo / VERSION_PATH
        self.path.write_bytes(b'__version__ = "1.2.3"\n')

    def test_patch_minor_major_and_explicit_versions(self):
        for change, expected in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0"), ("2.3.4", "2.3.4")):
            self.assertEqual(next_version("1.2.3", change), expected)

    def test_rejects_invalid_equal_or_lower_versions(self):
        for value in ("v2.0.0", "01.2.3", "1.2", "1.2.3", "1.0.0", "2.0.0rc1"):
            with self.assertRaises(ReleaseError):
                next_version("1.2.3", value)

    def test_dry_run_does_not_modify_and_update_needs_no_git(self):
        original = self.path.read_bytes()
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--dry-run"]), 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(main(["minor", "--repo", str(self.repo)]), 0)
        self.assertIn(b'"1.3.0"', self.path.read_bytes())

    def test_exact_tag_version_matching(self):
        self.assertEqual(check_tag(self.repo, "v1.2.3"), "1.2.3")
        for tag in ("1.2.3", "v1.2.4", "v01.2.3", "main", "v1.2.3-extra"):
            with self.assertRaises(ReleaseError):
                check_tag(self.repo, tag)


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitReleaseTests(VersionTests):
    def setUp(self):
        super().setUp()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def test_tag_implies_commit_and_changes_only_version_source(self):
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--tag"]), 0)
        self.assertEqual(self.git("tag", "--list"), "v1.2.4")
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), VERSION_PATH.as_posix())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dirty_repository_and_existing_tag_block_before_update(self):
        original = self.path.read_bytes()
        (self.repo / "unrelated.txt").write_bytes(b"do not commit")
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--tag"]), 2)
        self.assertEqual(self.path.read_bytes(), original)
        (self.repo / "unrelated.txt").unlink()
        self.git("tag", "v1.2.4")
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--tag"]), 2)
        self.assertEqual(self.path.read_bytes(), original)

    def test_push_creates_branch_and_tag_on_local_bare_remote(self):
        remote = Path(self.temporary.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--push"]), 0)
        refs = self.git("ls-remote", "origin")
        self.assertIn("refs/heads/main", refs)
        self.assertIn("refs/tags/v1.2.4", refs)

    def test_existing_remote_tag_blocks_without_local_changes(self):
        remote = Path(self.temporary.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("tag", "v1.2.4")
        self.git("push", "origin", "refs/tags/v1.2.4")
        self.git("tag", "--delete", "v1.2.4")
        original = self.path.read_bytes()
        self.assertEqual(main(["patch", "--repo", str(self.repo), "--push"]), 2)
        self.assertEqual(self.path.read_bytes(), original)
