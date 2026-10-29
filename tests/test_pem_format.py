"""PEM formatting templates are not embedded private keys."""
import re
import tempfile
import unittest
from pathlib import Path
from safe_repo_export.engine import Pseudonymizer, redact_source_text, scan_residuals

FORMAT = r'''            String result = String.format("-----BEGIN PRIVATE KEY-----\n" +
                    "%s\n" +
                    "-----END PRIVATE KEY-----", privatekeyBase64);'''


class PemFormatTests(unittest.TestCase):
    def scan(self, text, filename='Example.java'):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / filename).write_bytes(text.encode())
            return scan_residuals(Path(directory))

    def test_user_format_expression_preserved_and_not_flagged(self):
        for source in [FORMAT, FORMAT.replace('\n', '\r\n'), FORMAT.replace('PRIVATE KEY', 'RSA PRIVATE KEY')]:
            with self.subTest(source=source):
                self.assertEqual(redact_source_text(source, Pseudonymizer(b'test', set())), source)
                self.assertEqual(self.scan(source), [])

    def test_literal_or_additional_payload_and_incomplete_key_still_block(self):
        for source in [
            FORMAT.replace('privatekeyBase64', '"QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="'),
            FORMAT.replace('"%s\\n"', '"QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\\n"'),
            FORMAT.replace('"%s\\n"', '"QUJD%s\\n"'),
            '-----BEGIN PRIVATE KEY-----\nQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=',
            FORMAT + '\nString actual = "-----BEGIN PRIVATE KEY-----";',
        ]:
            with self.subTest(source=source):
                self.assertTrue(any(f['rule'] == 'private-key-block' for f in self.scan(source)))

    def test_safe_and_unsafe_markers_on_same_line_do_not_hide_each_other(self):
        source = FORMAT.replace('\n', ' ') + ' String actual = "-----BEGIN PRIVATE KEY-----";'
        findings = self.scan(source)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['line'], 1)

    def test_exemption_does_not_apply_to_comments_or_non_java(self):
        for source, filename in [('/* ' + FORMAT + ' */', 'Example.java'), (FORMAT, 'example.txt')]:
            with self.subTest(filename=filename):
                self.assertTrue(self.scan(source, filename))

    def test_actual_complete_embedded_key_is_redacted(self):
        source = r'String data = "-----BEGIN PRIVATE KEY-----\nQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\n-----END PRIVATE KEY-----";'
        result = redact_source_text(source, Pseudonymizer(b'test', set()))
        self.assertNotIn('QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=', result)
        self.assertIn('REDACTED_PRIVATE_KEY_BLOCK', result)
        self.assertEqual(self.scan(result), [])

    def test_documented_gitleaks_regexes_match_without_embedding_pem_header(self):
        patterns = [
            r'String\s+result\s*=\s*String\.format\("-{5}BEGIN PRIVATE KEY-{5}\\n"\s*\+',
            r'"%s\\n"\s*\+',
            r'"-{5}END PRIVATE KEY-{5}",\s*privatekeyBase64\);',
        ]
        for pattern, line in zip(patterns, FORMAT.splitlines()):
            self.assertIsNotNone(re.fullmatch(pattern, line.strip()))
        self.assertEqual(self.scan('\n'.join('regex:' + pattern for pattern in patterns),
                                   'safe-repo-export-gitleaks-ignore.list'), [])

    def test_other_secret_rules_still_apply_in_same_file(self):
        source = FORMAT + '\nString token = "ghp_' + 'A9bC2d' * 6 + '";'
        self.assertTrue(any(f['rule'] == 'github-token' for f in self.scan(source)))
