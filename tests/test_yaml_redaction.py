import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from safe_repo_export.engine import Pseudonymizer, read_list, redact_file


class YamlRedactionTests(unittest.TestCase):
    def redact(self, original):
        policies = Path(__file__).resolve().parents[1] / "safe_repo_export/policies"
        patterns = [re.compile(item, re.I) for item in read_list(policies / "safe-repo-export-redact-keys.list")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.yaml"
            path.write_bytes(original.encode())
            redact_file(path, patterns, Pseudonymizer(b"test", set()), Counter())
            return path.read_bytes().decode()

    def test_numbers_empty_values_and_nested_mapping_preserved(self):
        for value in ["1", "-2", "1.25", "1e3", "0xFF", "0o17", "true", "false", "null", "~",
                      "", "   ", '\" \"', "' '", '\"\"', "''", "1 # index", "# comment"]:
            with self.subTest(value=value):
                original = "settings:\r\n  seed-index: " + value + "\r\n"
                self.assertEqual(self.redact(original), original)
        original = "settings:\n  create-address:\n    enabled: true\n"
        self.assertEqual(self.redact(original), original)

    def test_sensitive_scalar_keeps_separator_comments_and_line_endings(self):
        for separator in [": ", ":   "]:
            original = "settings:\r\n  password" + separator + '\"fixture#secret\" # keep comment\r\n'
            expected = "settings:\r\n  password" + separator + '\"REDACTED_SECRET\" # keep comment\r\n'
            self.assertEqual(self.redact(original), expected)
        self.assertEqual(self.redact('password: \"123\"\n'), 'password: \"REDACTED_SECRET\"\n')

    def test_nonempty_address_value_keeps_yaml_mapping_space(self):
        result = self.redact("create-address: fixture-address\n")
        self.assertTrue(result.startswith('create-address: \"REDACTED_IDENTIFIER_'))
