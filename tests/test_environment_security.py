import unittest

from postbaby.environment import Environment, EnvironmentError
from postbaby.security import REDACTED, SecretRedactor


class EnvironmentTests(unittest.TestCase):
    def test_substitutes_multiple_values_without_mutating_source(self):
        source = 'url = "{{BASE_URL}}/{{TOKEN}}/{{USERNAME}}"'
        result = Environment({"BASE_URL": "https://api.example", "TOKEN": "abc", "USERNAME": "sam"}).substitute(source)
        self.assertEqual('url = "https://api.example/abc/sam"', result)
        self.assertIn("{{BASE_URL}}", source)

    def test_missing_and_unknown_values_are_useful_errors(self):
        with self.assertRaisesRegex(EnvironmentError, "Missing environment variable: USERNAME"):
            Environment({}).substitute("{{USERNAME}}")
        with self.assertRaisesRegex(EnvironmentError, "Unknown environment variable: REGION"):
            Environment({"BASE_URL": "x"}).substitute("{{REGION}}")

    def test_allows_empty_environment_variables(self):
        source = 'url = "{{BASE_URL}}/{{TOKEN}}/{{USERNAME}}"'
        result = Environment({"BASE_URL": "https://api.example", "TOKEN": "", "USERNAME": ""}).substitute(source)
        self.assertEqual('url = "https://api.example//"', result)

    def test_execution_ast_preserves_quotes_and_backslashes_in_values(self):
        source = 'def test_value():\n    assert "{{TOKEN}}" == "p\\\'a\\\\th"\n'
        tree = Environment({"TOKEN": "p'a\\th"}).substitute_ast(source)
        namespace = {}
        exec(compile(tree, "<test>", "exec"), namespace)
        namespace["test_value"]()


class SecurityTests(unittest.TestCase):
    def test_redacts_configured_values_and_authorization(self):
        redactor = SecretRedactor({"PASSWORD": "pw", "TOKEN": "token123", "API_KEY": "key456", "CLIENT_SECRET": "client"})
        text = "password=pw token123 key456 client Authorization: Bearer abc"
        result = redactor.redact(text)
        self.assertNotIn("token123", result)
        self.assertNotIn("key456", result)
        self.assertEqual("password=******** ******** ******** ******** Authorization: Bearer ********", result)

    def test_handles_none_and_empty_secrets(self):
        redactor = SecretRedactor({"TOKEN": None, "PASSWORD": ""})
        self.assertIsNone(redactor.redact(None))
        self.assertEqual("safe", redactor.redact("safe"))
