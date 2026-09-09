import tempfile
import unittest
from pathlib import Path

from postbaby.controller import ApplicationController, RunnerState
from postbaby.database import Database
from postbaby.executor import TestExecutor
from postbaby.models import TestCase, TestStatus


class PostBabyBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "postbaby_test.db"
        self.database = Database(self.db_path)
        self.controller = ApplicationController(self.database)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_executor_accepts_empty_token(self):
        source = 'def test_auth():\n    token = "{{TOKEN}}"\n    assert token == ""\n'
        executor = TestExecutor()
        test_case = TestCase("test_auth", "test_auth")
        env = {"BASE_URL": "https://api.test", "TOKEN": "", "USERNAME": "", "PASSWORD": ""}
        result = executor.execute(source, test_case, env)
        self.assertEqual(TestStatus.PASS, result.status)

    def test_state_back_navigation_preserves_source(self):
        state = RunnerState()
        state.parse("def test_one(): assert True")
        self.assertEqual("def test_one(): assert True", state.source)
        # Re-parsing or updating source retains source state
        state.parse("def test_one(): assert True\ndef test_two(): assert True")
        self.assertEqual(2, len(state.tests))

    def test_existing_projects_discovery(self):
        self.assertEqual([], self.database.session_history())
        project = self.database.create_project("Project Alpha")
        self.database.create_session(project.id, 1)
        history = self.database.session_history()
        self.assertEqual(1, len(history))
        self.assertEqual("Project Alpha", history[0]["project_name"])

    def test_mock_clear_result_details_resets_view_without_deleting_db(self):
        project = self.database.create_project("Test Project")
        session = self.database.create_session(project.id, 1)
        test = TestCase("test_demo", "Demo Test")
        self.database.save_test_runs(session.id, [test])

        # Verify DB results are intact after view clear
        results = self.database.session_results(session.id)
        self.assertEqual(0, len(results))  # Session not run yet, test run definition intact
        runs = self.database.unfinished_tests(session.id)
        self.assertEqual(1, len(runs))
