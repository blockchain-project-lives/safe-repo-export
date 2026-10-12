import unittest


class TestPublicHosts(unittest.TestCase):
    def test_regression(self):
        """Public host exceptions must apply before URL key redaction."""
        import importlib.util
        import json
        import re
        import tempfile
        from collections import Counter
        from pathlib import Path

        kit = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('export_helper', kit / 'safe_repo_export.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        patterns = [re.compile(item, re.I) for item in helper.read_list(kit / 'safe_repo_export/policies/safe-repo-export-redact-keys.list')]
        pseudo = helper.Pseudonymizer(b'test-only', {'maven.repository.redhat.com'})
        public = 'https://maven.repository.redhat.com/ga/'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixtures = {
                'pom.xml': '<project><repository><url>' + public + '</url></repository></project>',
                'application.yml': 'url: "' + public + '"\n',
                'config.json': json.dumps({'url': public}),
            }
            for name, text in fixtures.items():
                path = root / name
                path.write_text(text)
                helper.redact_file(path, patterns, pseudo, Counter())
                assert public in path.read_text(), name
            for value in [
                'https://user:password@maven.repository.redhat.com/ga/',
                'https://maven.repository.redhat.com/ga/?token=test',
                'https://private.internal/ga/',
            ]:
                assert helper.replacement_for_key('url', value, pseudo) != value
            assert helper.replacement_for_key('webhook-url', public, pseudo) != public
            assert helper.replacement_for_key('password', public, pseudo) == 'REDACTED_SECRET'
            assert not pseudo.is_public_url('https://@maven.repository.redhat.com/')
        print('PASS: public Maven URLs retained in XML/YAML/JSON; sensitive URLs and credential fields redact.')
