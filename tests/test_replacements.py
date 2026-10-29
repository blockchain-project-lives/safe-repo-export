import unittest
from safe_repo_export.replacements import (
    Rule, ReplacementError, load_rules, parse_config, replace_body, safe_relative,
)


class JavaReplacementTests(unittest.TestCase):
    def rule(self, **changes):
        fields = dict(file='Fee.java', class_name='demo.Fee', method='fee', parameters=('Order', 'BigDecimal'),
                      body='// Export-only mock\nreturn Result.zero();')
        fields.update(changes)
        return Rule(**fields)

    def test_nested_blocks_strings_comments_overload_and_signature(self):
        original = '''package demo;
class Fee {
    @Deprecated
    public <T> Result fee(final Order order, BigDecimal amount) throws Exception {
        // } original-confidential-comment
        String tricky = "{ }";
        Runnable task = new Runnable() { public void run() { secret(); } };
        if (true) { originalConfidentialLogic(); }
        return realResult();
    }
    Result fee(Order order) { return differentOverload(); }
}
'''
        result = replace_body(original, self.rule())
        self.assertIn('@Deprecated\n    public <T> Result fee(final Order order, BigDecimal amount) throws Exception {', result)
        self.assertIn('        return Result.zero();\n    }', result)
        self.assertIn('return differentOverload();', result)
        self.assertNotIn('originalConfidential', result)
        self.assertNotIn('realResult()', result)
        self.assertEqual(result[:result.index('throws Exception {')], original[:original.index('throws Exception {')])

    def test_nested_class_generics_annotations_varargs_arrays_and_crlf(self):
        source = '''package demo;
class Outer {
    static class Inner {
        Object fee(@Name(value="x,y") final java.util.Map<String, java.util.List<Order>> data,
                   String... values) { return secret(); }
    }
}
'''.replace('\n', '\r\n')
        rule = self.rule(class_name='demo.Outer.Inner', parameters=('java.util.Map<String,java.util.List<Order>>', 'String[]'))
        result = replace_body(source, rule)
        self.assertIn('return Result.zero();\r\n', result)
        self.assertNotIn('\n', result.replace('\r\n', ''))
        array = 'package demo; class Fee { Object fee(String names[]) { return secret(); } }'
        self.assertNotIn('secret()', replace_body(array, self.rule(parameters=('String[]',))))

    def test_text_block_and_annotation_array_do_not_change_brace_matching(self):
        source = '''package demo; class Fee {
  @Names({"x", "y"})
  Result fee(Order order, BigDecimal amount) {
    String data = """
      { notJava() }
      """;
    return secret();
  }
}'''
        result = replace_body(source, self.rule())
        self.assertIn('return Result.zero()', result)
        self.assertNotIn('notJava()', result)

    def test_missing_ambiguous_abstract_and_constructor_fail_closed(self):
        sources = [
            'package demo; class Fee { void different() {} }',
            'package demo; class Fee { Result fee(Order a, BigDecimal b); }',
            'package demo; class Fee { Result fee(Order a, BigDecimal b) {} Result fee(Order c, BigDecimal d) {} }',
            'package demo; class Fee {} class Fee {}',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ReplacementError):
                replace_body(source, self.rule())
        with self.assertRaises(ReplacementError):
            replace_body('package demo; class Fee { Fee() {} }', self.rule(method='Fee', parameters=()))

    def test_unterminated_unbalanced_and_unicode_escape_fail_closed(self):
        for source in ['class Fee {', 'class Fee { String a="missing; }', r'class Fee { // \u007d' + '\n}']:
            with self.subTest(source=source), self.assertRaises(ReplacementError):
                replace_body(source, self.rule())

    def test_parameter_names_can_change_and_zero_argument_methods(self):
        source = 'package demo; class Fee { Result fee(Order renamed, BigDecimal renamedAgain) { return secret(); } }'
        self.assertNotIn('secret()', replace_body(source, self.rule()))
        source = 'package demo; class Fee { Result fee() { return secret(); } }'
        self.assertNotIn('secret()', replace_body(source, self.rule(parameters=())))


CONFIG = '''replacements:
  - file: src/Fee.java
    class: demo.Fee
    method: fee
    parameter-types:
      - Order
      - BigDecimal
    body-file: stubs/fee.java.txt
'''


class ReplacementConfigTests(unittest.TestCase):
    def load(self, config=CONFIG, body=b'return Result.zero();'):
        files = {'.safe-repo-export/replacements.yaml': config.encode(), '.safe-repo-export/stubs/fee.java.txt': body}
        return load_rules(files.get)

    def test_disabled_missing_and_standard_example(self):
        self.assertEqual(load_rules(lambda name: None), [])
        self.assertEqual(self.load('replacements: []\n# disabled\n'), [])
        self.assertEqual(self.load()[0].parameters, ('Order', 'BigDecimal'))
        config = CONFIG.replace('    parameter-types:\n      - Order\n      - BigDecimal', '    parameter-types: []')
        self.assertEqual(self.load(config)[0].parameters, ())
        config = CONFIG.replace('src/Fee.java', '"src/Fee.java"').replace('stubs/fee.java.txt', "'stubs/fee.java.txt' # template")
        self.assertEqual(self.load(config)[0].file, 'src/Fee.java')

    def test_existing_java_extension_still_supported(self):
        files = {
            '.safe-repo-export/replacements.yaml': CONFIG.replace('stubs/fee.java.txt', 'stubs/legacy.java').encode(),
            '.safe-repo-export/stubs/legacy.java': b'return Result.zero();',
        }
        self.assertEqual(load_rules(files.get)[0].body, 'return Result.zero();')

    def test_unsupported_yaml_missing_duplicate_fields_and_missing_template(self):
        for config in [CONFIG + '    unknown: bad\n', CONFIG.replace('    class:', '    method:'),
                       CONFIG.replace('    class: demo.Fee\n', ''), CONFIG.replace('      - Order', '     - Order'),
                       CONFIG.replace('src/Fee.java', '*alias'), CONFIG.replace('    parameter-types:', '    parameter-types: [Order]')]:
            with self.subTest(config=config), self.assertRaises(ReplacementError):
                self.load(config)
        with self.assertRaises(ReplacementError):
            self.load(body=None)
        with self.assertRaises(ReplacementError):
            self.load(CONFIG + CONFIG.split('replacements:\n', 1)[1])
        with self.assertRaises(ReplacementError):
            self.load(body=b'return broken(;}')

    def test_path_traversal_absolute_paths_and_template_area(self):
        for path in ['../outside', '/etc/passwd', 'C:/outside', 'stubs/../file', 'stubs\\file', '.git/config']:
            with self.subTest(path=path), self.assertRaises(ReplacementError):
                safe_relative(path)
        with self.assertRaises(ReplacementError):
            self.load(CONFIG.replace('stubs/fee.java.txt', 'safe-repo-export-include.list'))
