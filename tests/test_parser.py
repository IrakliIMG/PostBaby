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

    def test_accepts_standard_library_modules_and_requests(self):
        source = (
            "import requests\n"
            "import uuid\n"
            "import base64\n"
            "import json\n"
            "import time\n"
            "import datetime\n"
            "import re\n"
            "import hashlib\n"
            "import hmac\n"
            "import secrets\n"
            "import os\n"
            "from urllib.parse import urljoin\n"
            "def test_all_allowed():\n"
            "    u = uuid.uuid4()\n"
            "    b = base64.b64encode(b'test')\n"
            "    assert u is not None\n"
        )
        result = validate_script(source)
        self.assertTrue(result.valid, f"Expected script to be valid, got errors: {result.errors}")
        self.assertEqual([], result.errors)

    def test_rejects_forbidden_third_party_packages(self):
        forbidden_packages = ["jwt", "httpx", "aiohttp", "faker", "selenium", "pandas"]
        for pkg in forbidden_packages:
            source = f"import {pkg}\ndef test_forbidden():\n    pass\n"
            result = validate_script(source)
            self.assertFalse(result.valid, f"Expected {pkg} to be rejected")
            self.assertIn(f"Unsupported import: {pkg}", result.errors)

    def test_rejects_forbidden_framework_and_execution_modules(self):
        forbidden_modules = ["pytest", "unittest", "subprocess", "shutil", "socket", "socketserver", "importlib"]
        for mod in forbidden_modules:
            source = f"import {mod}\ndef test_forbidden():\n    pass\n"
            result = validate_script(source)
            self.assertFalse(result.valid, f"Expected {mod} to be rejected")
            self.assertIn(f"Unsupported import: {mod}", result.errors)

    def test_rejects_dangerous_os_operations(self):
        dangerous_ops = ["remove", "rename", "system", "popen", "listdir", "unlink", "rmdir", "mkdir", "walk"]
        for op in dangerous_ops:
            source = f"import os\ndef test_bad():\n    os.{op}('dummy')\n"
            result = validate_script(source)
            self.assertFalse(result.valid, f"Expected os.{op} to be rejected")
            self.assertTrue(any(f"os.{op}" in err for err in result.errors), f"Missing error for os.{op}: {result.errors}")

    def test_rejects_dangerous_pathlib_filesystem_operations(self):
        dangerous_methods = ["unlink", "write_text", "write_bytes", "mkdir", "rmdir", "rename", "replace"]
        for method in dangerous_methods:
            source = f"from pathlib import Path\ndef test_bad():\n    Path('dummy').{method}()\n"
            result = validate_script(source)
            self.assertFalse(result.valid, f"Expected Path.{method} to be rejected")
            self.assertTrue(any(method in err for err in result.errors), f"Missing error for {method}: {result.errors}")

    def test_rejects_direct_forbidden_builtins(self):
        for builtin_call in ("open('file.txt')", "eval('1+1')", "exec('x=1')", "compile('1', '', 'exec')"):
            source = f"def test_bad():\n    {builtin_call}\n"
            result = validate_script(source)
            self.assertFalse(result.valid, f"Expected {builtin_call} to be rejected")
            self.assertTrue(any("not permitted" in err for err in result.errors), f"Missing error for {builtin_call}: {result.errors}")

    def test_allows_safe_os_and_pathlib_operations(self):
        source = (
            "import os\n"
            "from pathlib import Path\n"
            "def test_safe_env_and_path():\n"
            "    val = os.getenv('MY_VAR', 'default')\n"
            "    env_val = os.environ.get('BASE_URL')\n"
            "    joined = os.path.join('folder', 'sub')\n"
            "    p = Path('folder') / 'sub.json'\n"
            "    assert p.name == 'sub.json'\n"
            "    assert p.suffix == '.json'\n"
        )
        result = validate_script(source)
        self.assertTrue(result.valid, f"Expected safe os/pathlib script to be valid, got errors: {result.errors}")
        self.assertEqual([], result.errors)
