"""Helpful, deliberately light validation for the PostBaby script contract."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .parser import ParseResult, parse_script

ALLOWED_IMPORT_ROOTS = {"requests", "json", "re", "datetime", "time", "uuid", "random", "math", "typing", "collections", "urllib", "base64", "hashlib"}
FORBIDDEN_IMPORTS = {"pytest", "unittest", "subprocess", "os", "pathlib", "shutil", "socket", "selenium"}
SECRET_WORDS = re.compile(r"(password|token|api[_-]?key|client[_-]?secret|secret)", re.I)
URL = re.compile(r"https?://[^\s/'\"]+", re.I)


@dataclass(frozen=True)
class ValidationResult:
    parse_result: ParseResult
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_script(source: str) -> ValidationResult:
    parsed = parse_script(source)
    if parsed.syntax_error:
        return ValidationResult(parsed, [parsed.syntax_error], [])
    errors: list[str] = []
    warnings: list[str] = []
    for imported in parsed.imports:
        root = imported.split(".")[0]
        if root in FORBIDDEN_IMPORTS or root not in ALLOWED_IMPORT_ROOTS:
            errors.append(f"Unsupported import: {imported}")
    if not parsed.tests:
        errors.append("No test_* functions found")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
            errors.append(f"Async test functions are not supported: {node.name}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if URL.search(value) and "{{BASE_URL}}" not in value:
                warnings.append("Hardcoded base URL detected")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if any(isinstance(t, ast.Name) and SECRET_WORDS.search(t.id) for t in node.targets) and "{{" not in node.value.value:
                warnings.append("Possible hardcoded secret detected")
    return ValidationResult(parsed, _unique(errors), _unique(warnings))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
