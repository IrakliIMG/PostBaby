"""SQLite persistence. Secrets deliberately have no storage column in this MVP."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import Project, Session, SessionStatus, TestResult, TestStatus, utc_now


class Database:
    def __init__(self, path: str | Path = "postbaby.db") -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                status TEXT NOT NULL, total_tests INTEGER NOT NULL DEFAULT 0,
                completed_tests INTEGER NOT NULL DEFAULT 0, environment_metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS script_snapshots (
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                source TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_runs (
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                function_name TEXT NOT NULL, test_id TEXT, display_name TEXT NOT NULL, ordinal INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                function_name TEXT NOT NULL, test_id TEXT, status TEXT NOT NULL, duration_ms INTEGER,
                error_message TEXT, http_status INTEGER, details TEXT, completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS application_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
        """)
        self._add_column_if_missing("sessions", "environment_metadata", "TEXT NOT NULL DEFAULT '{}'")
        for name, definition in {
            "started_at": "TEXT", "http_method": "TEXT", "url": "TEXT", "response_body": "TEXT",
            "stdout": "TEXT", "stderr": "TEXT",
        }.items():
            self._add_column_if_missing("test_results", name, definition)
        self.connection.commit()

    def _add_column_if_missing(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_project(self, name: str) -> Project:
        now = utc_now()
        cursor = self.connection.execute("INSERT INTO projects(name, created_at) VALUES (?, ?)", (name, now))
        self.connection.commit()
        return Project(cursor.lastrowid, name, now)

    def get_or_create_project(self, name: str) -> Project:
        row = self.connection.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
        return Project(row["id"], row["name"], row["created_at"]) if row else self.create_project(name)

    def delete_project(self, project_id: int) -> bool:
        """Atomically delete a project and all its associated sessions, snapshots, runs, and results."""
        with self.connection:
            sessions = [
                row["id"]
                for row in self.connection.execute("SELECT id FROM sessions WHERE project_id=?", (project_id,)).fetchall()
            ]
            for session_id in sessions:
                self.connection.execute("DELETE FROM test_results WHERE session_id=?", (session_id,))
                self.connection.execute("DELETE FROM test_runs WHERE session_id=?", (session_id,))
                self.connection.execute("DELETE FROM script_snapshots WHERE session_id=?", (session_id,))
            self.connection.execute("DELETE FROM sessions WHERE project_id=?", (project_id,))
            cursor = self.connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return cursor.rowcount > 0

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.connection.execute("SELECT value FROM application_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO application_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.connection.commit()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT p.id, p.name, p.created_at,
                      COALESCE(MAX(s.updated_at), p.created_at) AS last_modified,
                      COUNT(s.id) AS session_count
               FROM projects p
               LEFT JOIN sessions s ON s.project_id=p.id
               GROUP BY p.id
               ORDER BY last_modified DESC, p.id DESC"""
        ).fetchall()

    def latest_project_script(self, project_id: int) -> Optional[str]:
        row = self.connection.execute(
            """SELECT ss.source
               FROM script_snapshots ss
               JOIN sessions s ON s.id=ss.session_id
               WHERE s.project_id=?
               ORDER BY ss.id DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        return row["source"] if row else None

    def latest_project_session(self, project_id: int) -> Optional[Session]:
        row = self.connection.execute(
            "SELECT * FROM sessions WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return self._session(row) if row else None

    def latest_project_environment(self, project_id: int) -> Optional[str]:
        row = self.connection.execute(
            "SELECT environment_metadata FROM sessions WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return row["environment_metadata"] if row else None

    def session_history(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT s.*, p.name AS project_name,
               SUM(CASE WHEN r.status='PASS' THEN 1 ELSE 0 END) AS passed,
               SUM(CASE WHEN r.status='FAIL' THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN r.status='ERROR' THEN 1 ELSE 0 END) AS errors
               FROM sessions s JOIN projects p ON p.id=s.project_id
               LEFT JOIN test_results r ON r.session_id=s.id AND r.status IN ('PASS','FAIL','ERROR')
               GROUP BY s.id ORDER BY s.id DESC"""
        ).fetchall()

    def session_results(self, session_id: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM test_results WHERE session_id=? AND status != ? ORDER BY id", (session_id, TestStatus.RUNNING)
        ).fetchall()

    def create_session(self, project_id: int, total_tests: int, environment_metadata: str = "{}") -> Session:
        now = utc_now()
        cursor = self.connection.execute(
            "INSERT INTO sessions(project_id, status, total_tests, environment_metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, SessionStatus.DRAFT, total_tests, environment_metadata, now, now),
        )
        self.connection.commit()
        return Session(cursor.lastrowid, project_id, SessionStatus.DRAFT, total_tests, 0, now, now)

    def set_session_status(self, session_id: int, status: SessionStatus) -> None:
        self.connection.execute("UPDATE sessions SET status=?, updated_at=? WHERE id=?", (status, utc_now(), session_id))
        self.connection.commit()

    def save_script_snapshot(self, session_id: int, source: str) -> int:
        cursor = self.connection.execute("INSERT INTO script_snapshots(session_id, source, created_at) VALUES (?, ?, ?)", (session_id, source, utc_now()))
        self.connection.commit()
        return cursor.lastrowid

    def save_test_runs(self, session_id: int, tests: list) -> None:
        self.connection.executemany(
            "INSERT INTO test_runs(session_id, function_name, test_id, display_name, ordinal) VALUES (?, ?, ?, ?, ?)",
            [(session_id, test.function_name, test.test_id, test.display_name, index) for index, test in enumerate(tests)],
        )
        self.connection.commit()

    def save_running_test(self, session_id: int, test) -> None:
        """Record an in-flight test before execution; recovery keeps it unfinished."""
        self.connection.execute(
            "INSERT INTO test_results(session_id, function_name, test_id, status, completed_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, test.function_name, test.test_id, TestStatus.RUNNING, utc_now()),
        )
        self.connection.commit()

    def save_test_result(self, result: TestResult) -> TestResult:
        """Commit a completed result immediately, so completed work survives a crash."""
        completed = result.completed_at or utc_now()
        # Replace the durable in-flight marker atomically. If a crash occurs before
        # this commit, the RUNNING marker remains available for recovery.
        previous_final = self.connection.execute(
            "SELECT 1 FROM test_results WHERE session_id=? AND function_name=? AND status IN (?, ?, ?, ?) LIMIT 1",
            (result.session_id, result.function_name, TestStatus.PASS, TestStatus.FAIL, TestStatus.ERROR, TestStatus.SKIPPED),
        ).fetchone()
        self.connection.execute("DELETE FROM test_results WHERE session_id=? AND function_name=?", (result.session_id, result.function_name))
        cursor = self.connection.execute(
            """INSERT INTO test_results(session_id, function_name, test_id, status, duration_ms,
               error_message, http_status, details, completed_at, started_at, http_method, url, response_body, stdout, stderr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.session_id, result.function_name, result.test_id, result.status, result.duration_ms,
             result.error_message, result.http_status, result.details, completed, result.started_at,
             result.http_method, result.url, result.response_body, result.stdout, result.stderr),
        )
        if not previous_final and result.status in {TestStatus.PASS, TestStatus.FAIL, TestStatus.ERROR, TestStatus.SKIPPED}:
            self.connection.execute("UPDATE sessions SET completed_tests=completed_tests+1, updated_at=? WHERE id=?", (completed, result.session_id))
        self.connection.commit()
        return TestResult(cursor.lastrowid, result.session_id, result.function_name, result.status, result.duration_ms,
                          result.test_id, result.error_message, result.http_status, result.details, completed, result.started_at,
                          result.http_method, result.url, result.response_body, result.stdout, result.stderr)

    def unfinished_tests(self, session_id: int) -> list:
        from .models import TestCase
        runs = self.connection.execute("SELECT function_name, test_id, display_name FROM test_runs WHERE session_id=? ORDER BY ordinal", (session_id,)).fetchall()
        final = self.connection.execute(
            "SELECT function_name FROM test_results WHERE session_id=? AND status IN (?, ?, ?, ?) GROUP BY function_name",
            (session_id, TestStatus.PASS, TestStatus.FAIL, TestStatus.ERROR, TestStatus.SKIPPED),
        ).fetchall()
        completed = {row["function_name"] for row in final}
        return [TestCase(row["function_name"], row["display_name"], row["test_id"]) for row in runs if row["function_name"] not in completed]

    def latest_script_snapshot(self, session_id: int) -> Optional[str]:
        row = self.connection.execute("SELECT source FROM script_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
        return row["source"] if row else None

    def recover_interrupted_sessions(self) -> list[Session]:
        """Mark unfinished sessions and their in-flight records interrupted on app startup."""
        rows = self.connection.execute("SELECT * FROM sessions WHERE status=?", (SessionStatus.RUNNING,)).fetchall()
        for row in rows:
            self.connection.execute("UPDATE sessions SET status=?, updated_at=? WHERE id=?", (SessionStatus.INTERRUPTED, utc_now(), row["id"]))
            self.connection.execute("UPDATE test_results SET status=? WHERE session_id=? AND status=?", (TestStatus.INTERRUPTED, row["id"], TestStatus.RUNNING))
        self.connection.commit()
        return [self._session(row, SessionStatus.INTERRUPTED) for row in rows]

    def get_session(self, session_id: int) -> Optional[Session]:
        row = self.connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._session(row) if row else None

    @staticmethod
    def _session(row: sqlite3.Row, status: Optional[SessionStatus] = None) -> Session:
        return Session(row["id"], row["project_id"], status or SessionStatus(row["status"]), row["total_tests"], row["completed_tests"], row["created_at"], row["updated_at"])
