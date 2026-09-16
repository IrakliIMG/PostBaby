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
        with self.assertRaisesRegex(EnvironmentError, "Missing environment variable: BASE_URL"):
            Environment({}).substitute("{{BASE_URL}}")
        with self.assertRaisesRegex(EnvironmentError, "Missing environment variable: BASE_URL"):
            Environment({"BASE_URL": ""}).substitute("{{BASE_URL}}")
        with self.assertRaisesRegex(EnvironmentError, "Missing environment variable: BASE_URL"):
            Environment({"BASE_URL": "   "}).substitute("{{BASE_URL}}")
        with self.assertRaisesRegex(EnvironmentError, "Unknown environment variable: REGION"):
            Environment({"BASE_URL": "x"}).substitute("{{REGION}}")

    def test_allows_empty_optional_environment_variables(self):
        env_all_empty = {
            "BASE_URL": "https://example.com",
            "TOKEN": "",
            "API_KEY": "",
            "USERNAME": "",
            "PASSWORD": "",
            "CLIENT_ID": "",
            "CLIENT_SECRET": "",
        }
        source = (
            'url="{{BASE_URL}}"\n'
            'token="{{TOKEN}}"\n'
            'key="{{API_KEY}}"\n'
            'user="{{USERNAME}}"\n'
            'pwd="{{PASSWORD}}"\n'
            'cid="{{CLIENT_ID}}"\n'
            'csec="{{CLIENT_SECRET}}"\n'
        )
        rendered = Environment(env_all_empty).substitute(source)
        self.assertIn('url="https://example.com"', rendered)
        self.assertIn('token=""', rendered)
        self.assertIn('key=""', rendered)
        self.assertIn('user=""', rendered)
        self.assertIn('pwd=""', rendered)
        self.assertIn('cid=""', rendered)
        self.assertIn('csec=""', rendered)

    def test_omitted_optional_variables_default_to_empty_string(self):
        source = 'u="{{USERNAME}}" t="{{TOKEN}}" k="{{API_KEY}}" p="{{PASSWORD}}" c="{{CLIENT_ID}}" s="{{CLIENT_SECRET}}"'
        rendered = Environment({"BASE_URL": "https://example.com"}).substitute(source)
        self.assertEqual('u="" t="" k="" p="" c="" s=""', rendered)

    def test_mixed_empty_and_populated_environments(self):
        env = {
            "BASE_URL": "https://api.example.com",
            "TOKEN": "tok_123",
            "API_KEY": "",
            "USERNAME": "testuser",
            "PASSWORD": "",
            "CLIENT_ID": "client_abc",
            "CLIENT_SECRET": "",
        }
        source = '{{BASE_URL}}/auth?user={{USERNAME}}&pass={{PASSWORD}}&tok={{TOKEN}}&key={{API_KEY}}&id={{CLIENT_ID}}&sec={{CLIENT_SECRET}}'
        rendered = Environment(env).substitute(source)
        self.assertEqual(
            'https://api.example.com/auth?user=testuser&pass=&tok=tok_123&key=&id=client_abc&sec=',
            rendered,
        )

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
