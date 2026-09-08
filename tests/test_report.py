import csv
import json
import tempfile
import unittest
from pathlib import Path

from postbaby.database import Database
from postbaby.models import SessionStatus, TestResult, TestStatus
from postbaby.parser import parse_script
from postbaby.report import ReportGenerator
from postbaby.session_manager import SessionManager


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.db = Database(self.root / "postbaby.db")
        project = self.db.create_project("SkyTel API")
        tests = parse_script("# TC-ONE\n# Health\ndef test_health():\n pass\n").tests
        self.session = SessionManager(self.db).create_session(project.id, "def test_health(): pass", tests, {"BASE_URL": "https://safe.example", "TOKEN": "secret-token"})
        self.db.save_test_result(TestResult(None, self.session.id, "test_health", TestStatus.FAIL, 143, "TC-ONE",
            "Invalid token secret-token", 401, "assertion secret-token", http_method="GET", url="https://safe.example/health",
            response_body='{"token":"secret-token"}', stdout="secret-token", stderr="Authorization: Bearer abc"))
        self.reports = ReportGenerator(self.db, {"TOKEN": "secret-token"})

    def tearDown(self): self.db.close(); self.temp.cleanup()

    def test_html_includes_sections_and_redacts(self):
        path = self.reports.generate_html_report(self.session.id, self.root / "report.html")
        text = path.read_text(encoding="utf-8")
        self.assertIn("POSTBABY", text); self.assertIn("Summary", text); self.assertIn("TC-ONE", text)
        self.assertNotIn("secret-token", text); self.assertIn("********", text)

    def test_json_is_structured_and_redacted(self):
        path = self.reports.generate_json_report(self.session.id, self.root / "report.json")
        data = json.loads(path.read_text())
        self.assertEqual("SkyTel API", data["project"]); self.assertEqual(1, data["summary"]["failed"])
        self.assertEqual("TC-ONE", data["tests"][0]["id"])
        self.assertNotIn("secret-token", path.read_text())

    def test_csv_has_headers_row_and_redaction(self):
        path = self.reports.generate_csv_report(self.session.id, self.root / "report.csv")
        with path.open(encoding="utf-8-sig", newline="") as stream: rows = list(csv.DictReader(stream))
        self.assertEqual(1, len(rows)); self.assertEqual("TC-ONE", rows[0]["Test ID"]); self.assertIn("HTTP Status", rows[0])
        self.assertNotIn("secret-token", path.read_text(encoding="utf-8-sig"))

    def test_empty_and_interrupted_sessions_export(self):
        project = self.db.get_or_create_project("Empty API")
        empty = self.db.create_session(project.id, 0); self.db.set_session_status(empty.id, SessionStatus.INTERRUPTED)
        data = self.reports.report_data(empty.id)
        self.assertEqual([], data["tests"]); self.assertEqual("INTERRUPTED", data["session"]["status"])
        self.reports.generate_html_report(empty.id, self.root / "empty.html")
        self.assertTrue((self.root / "empty.html").exists())

    def test_partially_completed_session_keeps_total_and_completed_counts(self):
        project = self.db.get_or_create_project("Partial API")
        partial = self.db.create_session(project.id, 2)
        self.db.save_test_result(TestResult(None, partial.id, "test_one", TestStatus.PASS, 5))
        data = self.reports.report_data(partial.id)
        self.assertEqual(2, data["summary"]["total"])
        self.assertEqual(1, data["summary"]["completed"])
        self.assertEqual(1, data["summary"]["passed"])
