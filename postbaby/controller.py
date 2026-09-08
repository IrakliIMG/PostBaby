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
