"""GUI-adjacent application state; designed to be tested without Tk."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .database import Database
from .models import TestCase
from .session_manager import SessionManager
from .validator import ValidationResult, validate_script


@dataclass
class RunnerState:
    source: str = ""
    tests: list[TestCase] = field(default_factory=list)
    selected: set[str] = field(default_factory=set)

    def parse(self, source: str) -> ValidationResult:
        self.source = source
        result = validate_script(source)
        self.tests = result.parse_result.tests if result.valid else []
        self.selected = {test.function_name for test in self.tests}
        return result

    def selected_tests(self) -> list[TestCase]:
        return [test for test in self.tests if test.function_name in self.selected]

    def set_selected(self, function_name: str, selected: bool) -> None:
        (self.selected.add if selected else self.selected.discard)(function_name)


class ApplicationController:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.state = RunnerState()
        self.sessions = SessionManager(database)

    def start_session(self, project_name: str, environment: Mapping[str, str | None], selected_only: bool = False):
        tests = self.state.selected_tests() if selected_only else self.state.tests
        if not project_name.strip():
            raise ValueError("Project name is required before running tests.")
        if not tests:
            raise ValueError("Parse a script and select at least one test first.")
        return self.sessions.create_session(self.database.get_or_create_project(project_name.strip()).id, self.state.source, tests, environment), tests

    def save_project(self, project_name: str, environment: Mapping[str, str | None], session_id: int | None = None):
        name = project_name.strip()
        if not name:
            raise ValueError("Project name cannot be empty.")
        project = self.database.get_or_create_project(name)
        import json
        from .models import utc_now
        safe_env = {k: environment.get(k, "") for k in ("BASE_URL", "USERNAME", "CLIENT_ID") if environment.get(k)}
        metadata = json.dumps(safe_env)
        tests = self.state.tests
        session = None
        if session_id:
            s_row = self.database.connection.execute("SELECT * FROM sessions WHERE id=? AND project_id=?", (session_id, project.id)).fetchone()
            if s_row:
                self.database.connection.execute(
                    "UPDATE sessions SET total_tests=?, environment_metadata=?, updated_at=? WHERE id=?",
                    (len(tests), metadata, utc_now(), session_id),
                )
                self.database.save_script_snapshot(session_id, self.state.source)
                existing_runs = self.database.connection.execute("SELECT COUNT(*) as c FROM test_runs WHERE session_id=?", (session_id,)).fetchone()["c"]
                if existing_runs == 0 and tests:
                    self.database.save_test_runs(session_id, tests)
                self.database.connection.commit()
                session = self.database.get_session(session_id)
        if not session:
            session = self.database.create_session(project.id, len(tests), metadata)
            self.database.save_script_snapshot(session.id, self.state.source)
            if tests:
                self.database.save_test_runs(session.id, tests)
        return project, session
