"""Core domain objects shared by PostBaby's application layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TestStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    INTERRUPTED = "INTERRUPTED"


class SessionStatus(StrEnum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"


FINAL_TEST_STATUSES = {TestStatus.PASS, TestStatus.FAIL, TestStatus.ERROR, TestStatus.SKIPPED}


@dataclass(frozen=True)
class TestCase:
    function_name: str
    display_name: str
    test_id: Optional[str] = None
    line_number: int = 0


@dataclass(frozen=True)
class Project:
    id: Optional[int]
    name: str
    created_at: str = ""


@dataclass(frozen=True)
class Session:
    id: Optional[int]
    project_id: int
    status: SessionStatus = SessionStatus.DRAFT
    total_tests: int = 0
    completed_tests: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TestResult:
    id: Optional[int]
    session_id: int
    function_name: str
    status: TestStatus
    duration_ms: Optional[int] = None
    test_id: Optional[str] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    details: Optional[str] = None
    completed_at: str = ""
    started_at: str = ""
    http_method: Optional[str] = None
    url: Optional[str] = None
    response_body: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
