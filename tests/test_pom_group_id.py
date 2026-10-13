import unittest


class TestPomGroupId(unittest.TestCase):
    def test_pom_class_names_urls_and_sensitive_values(self):
        import re
        import tempfile
        from collections import Counter
        from pathlib import Path
        from safe_repo_export.engine import Pseudonymizer, redact_file
        original = (
            '<project>\r\n'
            '<transformer implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer"/>\r\n'
            '<mainClass>com.example.Main</mainClass><version>1.2.3</version>\r\n'
            '<url>${repository.url}</url><name>httpExample.internal</name>\r\n'
            '<repository><url>https://private.internal/repo</url></repository>\r\n'
            '<url>https://public.example/repo</url>\r\n'
            "<repository url='https://private.internal/repo'/>\r\n"
            '<password>\r\nfixture-password\r\n</password>\r\n'
            '<configuration password="attribute-password"/>\r\n'
            '</project>\r\n'
        )
        patterns = [re.compile(r"^(password|url)$", re.I)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pom.xml"
            path.write_bytes(original.encode())
            redact_file(path, patterns, Pseudonymizer(b"test", {"public.example"}), Counter())
            result = path.read_bytes().decode()
            for value in ["org.apache.maven.plugins.shade.resource.ManifestResourceTransformer",
                          "com.example.Main", "1.2.3", "${repository.url}",
                          "httpExample.internal", "https://public.example/repo"]:
                self.assertIn(value, result)
            for value in ["private.internal", "fixture-password", "attribute-password"]:
                self.assertNotIn(value, result)
            self.assertIn("REDACTED_SECRET", result)
            self.assertNotIn("\n", result.replace("\r\n", ""))

    def test_regression(self):
        """Maven groupId coordinates remain intact without exempting the whole POM."""
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
        # Even an explicit groupId key rule must not anonymize Maven coordinates.
        patterns.append(re.compile('group_id', re.I))
        groups = ['<groupId>com.company.project</groupId>',
                  '<groupId>"com.vendor.library"</groupId>',
                  '<groupId>\n  org.example.plugin\n</groupId>',
                  '<m:groupId>org.example.parent</m:groupId>']
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'pom.xml'
            path.write_text('<project>\n' + '\n'.join(groups) +
                            '\n<password>test-sensitive-value</password>\n'
                            '<url>https://private.internal/repository</url>\n</project>')
            pseudo = helper.Pseudonymizer(b'test-only', set())
            helper.redact_file(path, patterns, pseudo, Counter())
            result = path.read_text()
            assert all(group in result for group in groups)
            assert 'test-sensitive-value' not in result
            assert 'private.internal' not in result
            assert 'SAFE_REPO_EXPORT_POM_GROUPID_' not in result
            helper.redact_file(path, patterns, pseudo, Counter())
            assert all(group in path.read_text() for group in groups)
        print('PASS: POM groupId preserved verbatim; password and private URL still redacted.')
