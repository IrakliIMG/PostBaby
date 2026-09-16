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

    def test_list_projects_and_latest_project_script(self):
        project = self.db.create_project("Project Omega")
        session1 = self.db.create_session(project.id, 1)
        self.db.save_script_snapshot(session1.id, "def test_v1(): pass")
        session2 = self.db.create_session(project.id, 2)
        self.db.save_script_snapshot(session2.id, "def test_v2(): pass")

        projects = self.db.list_projects()
        omega = next((p for p in projects if p["name"] == "Project Omega"), None)
        self.assertIsNotNone(omega)
        self.assertEqual(2, omega["session_count"])
        self.assertEqual("def test_v2(): pass", self.db.latest_project_script(project.id))

    def test_delete_project_cascades_all_related_data(self):
        project = self.db.create_project("Project To Delete")
        session = self.db.create_session(project.id, 2)
        self.db.save_script_snapshot(session.id, "def test_delete(): pass")
        self.db.save_test_runs(session.id, [type("T", (), {"function_name": "test_delete", "test_id": "TC-DEL", "display_name": "Del"})()])
        self.db.save_test_result(TestResult(None, session.id, "test_delete", TestStatus.PASS))

        # Ensure records exist
        self.assertEqual(1, len(self.db.session_results(session.id)))
        self.assertIsNotNone(self.db.get_session(session.id))

        # Delete project
        deleted = self.db.delete_project(project.id)
        self.assertTrue(deleted)

        # Verify project is gone
        projects = self.db.list_projects()
        self.assertNotIn("Project To Delete", [p["name"] for p in projects])

        # Verify session is gone
        self.assertIsNone(self.db.get_session(session.id))

        # Verify results, runs, snapshots are gone
        results = self.db.connection.execute("SELECT * FROM test_results WHERE session_id=?", (session.id,)).fetchall()
        self.assertEqual(0, len(results))
        runs = self.db.connection.execute("SELECT * FROM test_runs WHERE session_id=?", (session.id,)).fetchall()
        self.assertEqual(0, len(runs))
        snapshots = self.db.connection.execute("SELECT * FROM script_snapshots WHERE session_id=?", (session.id,)).fetchall()
        self.assertEqual(0, len(snapshots))

        # Deleting non-existent returns False
        self.assertFalse(self.db.delete_project(999999))

    def test_delete_project_leaves_unrelated_projects_and_settings_intact(self):
        proj_a = self.db.create_project("Keep Me")
        proj_b = self.db.create_project("Delete Me")

        sess_a = self.db.create_session(proj_a.id, 1)
        self.db.save_script_snapshot(sess_a.id, "def test_keep(): pass")
        self.db.save_test_result(TestResult(None, sess_a.id, "test_keep", TestStatus.PASS))

        sess_b = self.db.create_session(proj_b.id, 1)
        self.db.save_script_snapshot(sess_b.id, "def test_del(): pass")

        self.db.set_setting("theme", "dark")
        self.db.set_setting("custom_key", "custom_val")

        self.assertTrue(self.db.delete_project(proj_b.id))

        # Project A and its data remain completely untouched
        self.assertIsNotNone(self.db.get_session(sess_a.id))
        self.assertEqual(1, len(self.db.session_results(sess_a.id)))
        self.assertEqual("def test_keep(): pass", self.db.latest_project_script(proj_a.id))

        # Global settings remain completely untouched
        self.assertEqual("dark", self.db.get_setting("theme"))
        self.assertEqual("custom_val", self.db.get_setting("custom_key"))

    def test_theme_setting_persistence(self):
        self.assertIsNone(self.db.get_setting("theme"))
        self.assertEqual("default_dark", self.db.get_setting("theme", "default_dark"))

        self.db.set_setting("theme", "light")
        self.assertEqual("light", self.db.get_setting("theme"))

        # Re-open database to verify persistence on disk
        path = self.db.path
        self.db.close()
        reopened = Database(path)
        self.assertEqual("light", reopened.get_setting("theme"))
        reopened.close()

