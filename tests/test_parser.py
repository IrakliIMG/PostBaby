import unittest

from postbaby.parser import parse_script
from postbaby.validator import validate_script


class ParserAndValidatorTests(unittest.TestCase):
    def test_discovers_tests_and_comment_metadata(self):
        source = "# TC-AUTH-001\n# Login works\ndef test_login_success():\n    pass\n"
        result = parse_script(source)
        self.assertEqual(1, len(result.tests))
        self.assertEqual("TC-AUTH-001", result.tests[0].test_id)
        self.assertEqual("Login works", result.tests[0].display_name)

    def test_reports_syntax_error(self):
        result = validate_script("def test_broken(:\n    pass")
        self.assertFalse(result.valid)
        self.assertIn("Syntax error on line 1", result.errors[0])

    def test_rejects_unsupported_import(self):
        result = validate_script("import selenium\ndef test_browser():\n    pass")
        self.assertIn("Unsupported import: selenium", result.errors)

    def test_warns_on_url_and_secret(self):
        result = validate_script('password = "not-safe"\ndef test_call():\n    url = "https://example.com/x"')
        self.assertIn("Hardcoded base URL detected", result.warnings)
        self.assertIn("Possible hardcoded secret detected", result.warnings)

    def test_rejects_async_test_that_cannot_be_executed_synchronously(self):
        result = validate_script("async def test_async():\n    return True")
        self.assertFalse(result.valid)
        self.assertIn("Async test functions are not supported: test_async", result.errors)
