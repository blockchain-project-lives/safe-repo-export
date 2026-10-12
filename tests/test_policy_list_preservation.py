import unittest


class TestPolicyListPreservation(unittest.TestCase):
    def test_regression(self):
        """Exported matching policies must keep their original bytes."""
        import importlib.util
        import re
        import tempfile
        from collections import Counter
        from pathlib import Path
        kit = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('helper', kit / 'safe_repo_export.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        patterns = [re.compile(item, re.I) for item in helper.read_list(kit / 'safe_repo_export/policies/safe-repo-export-redact-keys.list')]
        pseudo = helper.Pseudonymizer(b'test-only', set())
        original = (
            b'String walletPassword = "example-value";\r\n'
            b'regex:String\\s+apiKey\\s*=.*;\r\n'
            b'path:src/main/resources/mybatis/mappers/*.xml\r\n'
            b'https://private.internal/path\r\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in ['.safe-repo-export/safe-repo-export-gitleaks-ignore.list', 'custom.list', 'CUSTOM.LIST']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
                counts = Counter()
                helper.redact_file(path, patterns, pseudo, counts)
                assert path.read_bytes() == original
                assert counts['list_files_preserved'] == 1
                assert counts['files_redacted'] == 0
            config = root / 'application.yml'
            config.write_text('password: "example-value"\n')
            helper.redact_file(config, patterns, pseudo, Counter())
            assert 'example-value' not in config.read_text()
        print('PASS: .list files preserved byte-for-byte; application config still redacted.')
