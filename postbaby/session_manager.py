"""Session creation and resume selection, independent of any GUI."""

from __future__ import annotations

import json
from typing import Mapping

from .database import Database
from .models import Session, TestCase


class SessionManager:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_session(self, project_id: int, source: str, tests: list[TestCase], environment: Mapping[str, str | None]) -> Session:
        session = self.database.create_session(project_id, len(tests), json.dumps({"BASE_URL": environment.get("BASE_URL", "")}))
        self.database.save_script_snapshot(session.id, source)
        self.database.save_test_runs(session.id, tests)
        return session

    def resume_tests(self, session_id: int) -> list[TestCase]:
        return self.database.unfinished_tests(session_id)
