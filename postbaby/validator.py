"""Helpful, deliberately light validation for the PostBaby script contract."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass

from .parser import ParseResult, parse_script

_COMMON_STDLIB = frozenset({
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect", "builtins",
    "calendar", "cmath", "collections", "colorsys", "concurrent", "contextlib", "contextvars",
    "copy", "copyreg", "csv", "ctypes", "dataclasses", "datetime", "decimal", "difflib",
    "dis", "doctest", "email", "enum", "errno", "faulthandler", "fcntl", "filecmp",
    "fileinput", "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
    "gettext", "glob", "graphlib", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "imaplib", "imghdr", "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nntplib", "numbers",
    "operator", "optparse", "os", "pathlib", "pdb", "pickle", "pickletools", "pipes",
    "pkgutil", "platform", "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random",
    "re", "readline", "reprlib", "resource", "rlcompleter", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib",
    "sndhdr", "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics", "string",
    "stringprep", "struct", "symtable", "sys", "sysconfig", "syslog", "tarfile", "telnetlib",
    "tempfile", "termios", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo",
    "types", "typing", "unicodedata", "urllib", "uu", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml",
    "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo"
})

_DISCOVERED_STDLIB = (frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(sys.builtin_module_names)) or _COMMON_STDLIB
FORBIDDEN_IMPORTS = frozenset({
    "pytest", "unittest", "subprocess", "shutil", "socket", "socketserver",
    "importlib", "imp", "ctypes"
})
ALLOWED_IMPORT_ROOTS = (frozenset({"requests"}) | _DISCOVERED_STDLIB) - FORBIDDEN_IMPORTS

DANGEROUS_OS_ATTRIBUTES = frozenset({
    "system", "popen", "remove", "unlink", "rename", "replace",
    "rmdir", "mkdir", "makedirs", "listdir", "scandir", "walk",
    "chmod", "chown", "truncate", "kill", "killpg", "fork",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
    "spawnvp", "spawnvpe", "startfile"
})

DANGEROUS_PATH_ATTRIBUTES = frozenset({
    "unlink", "write_text", "write_bytes", "mkdir", "rmdir",
    "rename", "replace", "touch", "chmod", "symlink_to", "hardlink_to"
})

FORBIDDEN_BUILTIN_CALLS = frozenset({"open", "eval", "exec", "compile"})


def is_allowed_import(name: str) -> bool:
    root = name.split(".")[0]
    return root in ALLOWED_IMPORT_ROOTS
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
        if not is_allowed_import(root):
            errors.append(f"Unsupported import: {imported}")
    if not parsed.tests:
        errors.append("No test_* functions found")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
            errors.append(f"Async test functions are not supported: {node.name}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTIN_CALLS:
                errors.append(f"Direct operation is not permitted: {node.func.id}()")
        if isinstance(node, ast.ImportFrom):
            if node.module == "os":
                for alias in node.names:
                    if alias.name in DANGEROUS_OS_ATTRIBUTES:
                        errors.append(f"Dangerous OS operation is not allowed: os.{alias.name}")
            elif node.module == "pathlib":
                for alias in node.names:
                    if alias.name in DANGEROUS_PATH_ATTRIBUTES:
                        errors.append(f"Dangerous filesystem operation is not allowed: {alias.name}")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in DANGEROUS_OS_ATTRIBUTES:
                errors.append(f"Dangerous OS operation is not allowed: os.{node.attr}")
            elif node.attr in DANGEROUS_PATH_ATTRIBUTES:
                errors.append(f"Dangerous filesystem operation is not allowed: {node.attr}")
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
