"""Controlled execution of one AST-discovered test at a time."""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import time
import traceback
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Mapping

from .environment import Environment, EnvironmentError
from .models import TestCase, TestResult, TestStatus, utc_now
from .security import SecretRedactor
from .validator import ALLOWED_IMPORT_ROOTS, DANGEROUS_OS_ATTRIBUTES, is_allowed_import, validate_script


class _SafeOsProxy:
    """Restricted proxy for os module allowing safe environment/path queries while blocking dangerous system/fs operations."""

    def __init__(self, real_os: Any) -> None:
        self._real_os = real_os

    def __getattr__(self, name: str) -> Any:
        if name in DANGEROUS_OS_ATTRIBUTES:
            raise PermissionError(f"os.{name}() is disabled in PostBaby for security.")
        return getattr(self._real_os, name)

    def __dir__(self) -> list[str]:
        return [attr for attr in dir(self._real_os) if attr not in DANGEROUS_OS_ATTRIBUTES]


def _wrap_path_class(cls: type) -> type:
    class SafePath(cls):
        def unlink(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.unlink() is disabled in PostBaby for security.")

        def write_text(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.write_text() is disabled in PostBaby for security.")

        def write_bytes(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.write_bytes() is disabled in PostBaby for security.")

        def mkdir(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.mkdir() is disabled in PostBaby for security.")

        def rmdir(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.rmdir() is disabled in PostBaby for security.")

        def rename(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.rename() is disabled in PostBaby for security.")

        def replace(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.replace() is disabled in PostBaby for security.")

        def touch(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.touch() is disabled in PostBaby for security.")

        def chmod(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Path.chmod() is disabled in PostBaby for security.")

    SafePath.__name__ = cls.__name__
    return SafePath


class _SafePathlibProxy:
    """Restricted proxy for pathlib module disabling mutating filesystem methods on Path."""

    def __init__(self, real_pathlib: Any) -> None:
        self._real_pathlib = real_pathlib

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._real_pathlib, name)
        if name in ("Path", "PosixPath", "WindowsPath") and isinstance(attr, type):
            return _wrap_path_class(attr)
        return attr

    def __dir__(self) -> list[str]:
        return dir(self._real_pathlib)


@dataclass(frozen=True)
class ExecutionResult:
    status: TestStatus
    duration_ms: int
    error_message: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    http_method: str | None = None
    url: str | None = None
    http_status: int | None = None
    response_body: str | None = None
    started_at: str = ""
    completed_at: str = ""

    def to_test_result(self, session_id: int, test: TestCase) -> TestResult:
        return TestResult(None, session_id, test.function_name, self.status, self.duration_ms, test.test_id,
                          self.error_message, self.http_status, None, self.completed_at, self.started_at,
                          self.http_method, self.url, self.response_body, self.stdout, self.stderr)


class _RequestsRecorder:
    def __init__(self) -> None:
        self.last: dict[str, Any] = {}

    def module(self) -> ModuleType:
        import requests
        module = ModuleType("requests")
        for name in ("get", "post", "put", "patch", "delete", "head", "options", "request"):
            setattr(module, name, self._wrap(name, getattr(requests, name)))
        module.exceptions = requests.exceptions
        return module

    def _wrap(self, name: str, function: Any):
        def call(*args: Any, **kwargs: Any) -> Any:
            response = function(*args, **kwargs)
            request = response.request
            self.last = {"method": request.method or name.upper(), "url": request.url,
                         "status": response.status_code, "body": response.text}
            return response
        return call


class TestExecutor:
    def execute(self, source: str, test: TestCase, environment: Mapping[str, str | None]) -> ExecutionResult:
        validation = validate_script(source)
        started = utc_now()
        if not validation.valid:
            return ExecutionResult(TestStatus.ERROR, 0, "; ".join(validation.errors), started_at=started, completed_at=utc_now())
        if test.function_name not in {item.function_name for item in validation.parse_result.tests}:
            return ExecutionResult(TestStatus.ERROR, 0, f"Unknown test function: {test.function_name}", started_at=started, completed_at=utc_now())
        redactor = SecretRedactor(environment)
        try:
            rendered = Environment(environment).substitute_ast(source)
        except EnvironmentError as error:
            return ExecutionResult(TestStatus.ERROR, 0, redactor.redact(error), started_at=started, completed_at=utc_now())
        recorder = _RequestsRecorder()
        stdout, stderr = io.StringIO(), io.StringIO()
        begin = time.perf_counter()
        status, message = TestStatus.PASS, None
        try:
            namespace = self._namespace(rendered, test.function_name, recorder)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                namespace[test.function_name]()
        except AssertionError as error:
            status, message = TestStatus.FAIL, str(error) or "Assertion failed"
        except Exception as error:  # execution details are captured as an ERROR, not a failed assertion
            status, message = TestStatus.ERROR, f"{type(error).__name__}: {error}"
        duration = round((time.perf_counter() - begin) * 1000)
        info = recorder.last
        return ExecutionResult(status, duration, redactor.redact(message), redactor.redact(stdout.getvalue()) or None,
                               redactor.redact(stderr.getvalue()) or None, info.get("method"), redactor.redact(info.get("url")),
                               info.get("status"), redactor.redact(info.get("body")), started, utc_now())

    @staticmethod
    def _namespace(tree: ast.Module, function_name: str, recorder: _RequestsRecorder) -> dict[str, Any]:
        selected = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom)) or
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name]
        safe_builtins = dict(vars(builtins))
        # This enforces the documented contract against accidental direct file,
        # interactive, and dynamic-code operations. It is not a security sandbox.
        for name in ("open", "input", "breakpoint", "eval", "exec", "compile"):
            safe_builtins.pop(name, None)
        normal_import = builtins.__import__
        def importer(name: str, *args: Any, **kwargs: Any) -> Any:
            root = name.split(".")[0]
            if not is_allowed_import(root):
                raise ImportError(f"Unsupported import: {name}")
            if name == "requests":
                return recorder.module()
            module = normal_import(name, *args, **kwargs)
            if root == "os":
                return _SafeOsProxy(module)
            if root == "pathlib":
                return _SafePathlibProxy(module)
            return module
        safe_builtins["__import__"] = importer
        namespace: dict[str, Any] = {"__builtins__": safe_builtins, "__name__": "__postbaby_test__"}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "<postbaby-script>", "exec"), namespace)
        return namespace
