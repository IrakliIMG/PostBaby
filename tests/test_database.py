import tempfile
import unittest
from pathlib import Path

from postbaby.database import Database
from postbaby.models import SessionStatus, TestResult, TestStatus


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "postbaby.db")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_creates_session_and_saves_result_immediately(self):
        project = self.db.create_project("SkyTel API")
        session = self.db.create_session(project.id, 2)
        saved = self.db.save_test_result(TestResult(None, session.id, "test_health", TestStatus.PASS, 42))
        self.assertIsNotNone(saved.id)
        current = self.db.get_session(session.id)
        self.assertEqual(1, current.completed_tests)

    def test_recovers_running_session(self):
        project = self.db.create_project("API")
        session = self.db.create_session(project.id, 1)
        self.db.set_session_status(session.id, SessionStatus.RUNNING)
        recovered = self.db.recover_interrupted_sessions()
        self.assertEqual([session.id], [item.id for item in recovered])
        self.assertEqual(SessionStatus.INTERRUPTED, self.db.get_session(session.id).status)

    def test_rerunning_same_test_does_not_duplicate_progress_or_results(self):
        project = self.db.create_project("Repeat API")
        session = self.db.create_session(project.id, 1)
        for status in (TestStatus.FAIL, TestStatus.PASS):
            self.db.save_running_test(session.id, type("Test", (), {"function_name": "test_health", "test_id": None})())
            self.db.save_test_result(TestResult(None, session.id, "test_health", status))
        self.assertEqual(1, self.db.get_session(session.id).completed_tests)
        self.assertEqual(1, len(self.db.session_results(session.id)))
        self.assertEqual(TestStatus.PASS, self.db.session_results(session.id)[0]["status"])
