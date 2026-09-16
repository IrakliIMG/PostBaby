"""Runtime-only environment substitution; source scripts are never changed."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Mapping

SUPPORTED_VARIABLES = {"BASE_URL", "TOKEN", "API_KEY", "USERNAME", "PASSWORD", "CLIENT_ID", "CLIENT_SECRET"}
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


class EnvironmentError(ValueError):
    pass


@dataclass(frozen=True)
class Environment:
    values: Mapping[str, str | None]

    def substitute(self, source: str) -> str:
        """Render placeholders for display or non-code data without changing source."""
        return PLACEHOLDER.sub(self._replacement(), source)

    def substitute_ast(self, source: str) -> ast.Module:
        """Safely render placeholders inside Python string literals for execution.

        Modifying AST string constants rather than Python source preserves values such
        as quotes and backslashes in credentials without producing invalid code.
        """
        replacement = self._replacement()
        tree = ast.parse(source)

        class SubstituteStrings(ast.NodeTransformer):
            def visit_Constant(self, node: ast.Constant):  # noqa: N802 - AST API name
                if isinstance(node.value, str):
                    return ast.copy_location(ast.Constant(value=PLACEHOLDER.sub(replacement, node.value)), node)
                return node

        return ast.fix_missing_locations(SubstituteStrings().visit(tree))

    def _replacement(self):
        missing: set[str] = set()
        unknown: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in SUPPORTED_VARIABLES:
                unknown.add(name)
                return match.group(0)
            value = self.values.get(name)
            if name == "BASE_URL":
                if value is None or not str(value).strip():
                    missing.add(name)
                    return match.group(0)
                return str(value)
            if value is None:
                return ""
            return str(value)

        def checked_replace(match: re.Match[str]) -> str:
            value = replace(match)
            if missing:
                raise EnvironmentError("Missing environment variable: " + ", ".join(sorted(missing)))
            if unknown:
                raise EnvironmentError("Unknown environment variable: " + ", ".join(sorted(unknown)))
            return value

        return checked_replace

    def safe_values(self) -> dict[str, str]:
        """Configuration safe to associate with a session snapshot."""
        return {"BASE_URL": str(self.values.get("BASE_URL", ""))}
