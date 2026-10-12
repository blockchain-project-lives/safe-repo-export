import unittest


class TestSourceRedaction(unittest.TestCase):
    def test_regression(self):
        import importlib.util,tempfile,re,ast,json
        from pathlib import Path
        from collections import Counter
        kit=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('helper',kit/'safe_repo_export.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        patterns=[re.compile(x,re.I) for x in m.read_list(kit/'safe_repo_export/policies/safe-repo-export-redact-keys.list')]
        pseudo=m.Pseudonymizer(b'test',set())
        topic='0x'+'a1'*32;address='0x'+'B2'*20
        preserve=[f'String topic = "{topic}";',f'String walletAddress = "{address}";','private final static String INVALID_SENDER = "fixedBusinessConstant";','String sender = "aBusinessIdentifier123456789abcdefgh";','String key1 = "'+'ab'*32+'";','String rpcUrl = "https://internal.example.com";','String text = ", signing_key=\'abc\'" + "end";','String text = "password=\\\"quotedContent\\\"";']
        for text in preserve:assert m.redact_source_text(text,pseudo)==text,text
        keyword_names = ["transactionPassword", "verificationCode", "signedTransaction",
                         "keystorePassword", "mnemonicPhrase", "refreshToken", "privateKey",
                         "clientSecret", "accessToken", "seedPhrase", "apiKey", "password"]
        keyword_constants = (
            'private static final String ENGLISH_SECRET_KEYWORDS =\n' +
            ' +\n'.join('    "' + name + '|"' for name in keyword_names) + ';\n' +
            'private static final String CHINESE_SECRET_KEYWORDS =\n' +
            '    "交易密码|" +\n    "私钥|" +\n    "种子";'
        )
        assert m.redact_source_text(keyword_constants, pseudo) == keyword_constants
        assert m.redact_source_text('const secretKeywords = "password|apiKey";', pseudo) == 'const secretKeywords = "password|apiKey";'
        assert m.redact_source_text('String PASSWORD_PATTERN = "[a-z0-9]+";', pseudo) == 'String PASSWORD_PATTERN = "[a-z0-9]+";'
        # Metadata names do not exempt recognizable actual secret formats.
        assert 'ghp_' + 'A9bC2d' * 6 not in m.redact_source_text('String SECRET_KEYWORDS = "ghp_' + 'A9bC2d' * 6 + '";', pseudo)
        secret_cases=['String signingKey = "sensitive-value";','const apiKey = "sensitive-value";','api_key = "sensitive-value"','authKey := "sensitive-value"','var privateKey string = "sensitive-value"','headers.put("authKey", "sensitive-value");','const settings = {"apiKey": "sensitive-value"};']
        for text in secret_cases:assert 'sensitive-value' not in m.redact_source_text(text,pseudo),text
        assert m.redact_source_text('password = ""',pseudo)=='password = ""'
        assert m.redact_source_text('password = "${PASSWORD}"',pseudo)=='password = "${PASSWORD}"'
        telegram='123456789:'+('Ab_9-'*7)
        assert telegram not in m.redact_source_text('const bot = "'+telegram+'";',pseudo)
        assert "test-user:test-password@" not in m.redact_source_text('String url = "https://test-user:test-password@example.invalid/path";',pseudo)
        python_source='api_key = "sensitive-value"\ntext = "signing_key=\'abc\'"\n'
        python_result=m.redact_source_text(python_source,pseudo);ast.parse(python_result)
        assert 'signing_key=\'abc\'' in python_result
        with tempfile.TemporaryDirectory() as td:
         root=Path(td)
         for ext in ['.java','.js','.py','.go']:
          p=root/('Test'+ext);original='\n'.join(preserve);p.write_text(original);m.redact_file(p,patterns,pseudo,Counter());assert p.read_text()==original
         p=root/'application.yml';p.write_text('sender: "business-identifier"\npassword: "sensitive-value"\ntopic: "'+topic+'"\n');m.redact_file(p,patterns,pseudo,Counter());assert 'sensitive-value' not in p.read_text() and topic not in p.read_text()
        print('PASS: Java/JS/Python/Go preserve topics, addresses, hex and business constants; credential fields and Telegram tokens redact; embedded assignment text/escaping preserved; YAML remains strict.')
