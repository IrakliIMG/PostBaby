"""AST-only script inspection; this module never executes user code."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .models import TestCase


@dataclass(frozen=True)
class ParseResult:
    tests: list[TestCase]
    imports: list[str]
    syntax_error: str | None = None


def parse_script(source: str) -> ParseResult:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return ParseResult([], [], f"Syntax error on line {error.lineno}: {error.msg}")

    imports: list[str] = []
    tests: list[TestCase] = []
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            test_id, title, start_line = _metadata(lines, node.lineno)
            end_line = getattr(node, "end_lineno", node.lineno)
            display = title or node.name.removeprefix("test_").replace("_", " ").title()
            tests.append(TestCase(node.name, display, test_id, node.lineno, start_line, end_line))
    return ParseResult(tests, imports)


def _metadata(lines: list[str], function_line: int) -> tuple[str | None, str | None, int]:
    comments: list[str] = []
    index = function_line - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        comments.append(lines[index].strip()[1:].strip())
        index -= 1
    comments.reverse()
    test_id = next((value for value in comments if re.fullmatch(r"TC-[A-Z0-9-]+", value)), None)
    title = next((value for value in comments if value != test_id), None)
    comment_start = index + 2 if comments else function_line
    return test_id, title, comment_start

