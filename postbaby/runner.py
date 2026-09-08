"""Sequential runner that persists every transition before moving on."""

from __future__ import annotations

from typing import Mapping, Sequence

from .database import Database
from .executor import TestExecutor
from .models import SessionStatus, TestCase, TestStatus


class TestRunner:
    def __init__(self, database: Database, executor: TestExecutor | None = None) -> None:
        self.database, self.executor, self._stop_requested = database, executor or TestExecutor(), False

    def stop(self) -> None:
        self._stop_requested = True

    def run_one(self, session_id: int, source: str, test: TestCase, environment: Mapping[str, str | None], **callbacks):
        return self._run(session_id, source, [test], environment, **callbacks)

    def run_selected(self, session_id: int, source: str, tests: Sequence[TestCase], environment: Mapping[str, str | None], **callbacks):
        return self._run(session_id, source, tests, environment, **callbacks)

    def run_all(self, session_id: int, source: str, tests: Sequence[TestCase], environment: Mapping[str, str | None], **callbacks):
        return self._run(session_id, source, tests, environment, **callbacks)

    def resume(self, session_id: int, source: str, environment: Mapping[str, str | None], **callbacks):
        return self._run(session_id, source, self.database.unfinished_tests(session_id), environment, **callbacks)

    def _run(self, session_id: int, source: str, tests: Sequence[TestCase], environment: Mapping[str, str | None], on_started=None, on_result=None):
        self._stop_requested = False
        self.database.set_session_status(session_id, SessionStatus.RUNNING)
        outcomes = []
        for test in tests:
            if self._stop_requested:
                break
            self.database.save_running_test(session_id, test)
            if on_started:
                on_started(test)
            result = self.executor.execute(source, test, environment).to_test_result(session_id, test)
            saved = self.database.save_test_result(result)
            outcomes.append(saved)
            if on_result:
                on_result(saved)
        self.database.set_session_status(session_id, SessionStatus.PAUSED if self._stop_requested else SessionStatus.COMPLETE)
        return outcomes
