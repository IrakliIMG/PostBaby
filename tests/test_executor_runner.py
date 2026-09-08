import tempfile
import unittest
from pathlib import Path

from postbaby.database import Database
from postbaby.executor import ExecutionResult, TestExecutor
from postbaby.models import SessionStatus, TestCase, TestStatus
from postbaby.parser import parse_script
from postbaby.runner import TestRunner
from postbaby.session_manager import SessionManager


PASS_FAIL_ERROR = """
def test_pass():
    print('token=topsecret')
    assert True

def test_fail():
    assert False, 'token topsecret leaked'

def test_error():
    raise RuntimeError('token topsecret leaked')
"""


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tests = {item.function_name: item for item in parse_script(PASS_FAIL_ERROR).tests}
        self.executor = TestExecutor()
        self.environment = {"TOKEN": "topsecret"}

    def test_classifies_and_redacts_results(self):
        passed = self.executor.execute(PASS_FAIL_ERROR, self.tests["test_pass"], self.environment)
        failed = self.executor.execute(PASS_FAIL_ERROR, self.tests["test_fail"], self.environment)
        errored = self.executor.execute(PASS_FAIL_ERROR, self.tests["test_error"], self.environment)
        self.assertEqual(TestStatus.PASS, passed.status)
        self.assertGreaterEqual(passed.duration_ms, 0)
        self.assertNotIn("topsecret", passed.stdout)
        self.assertEqual(TestStatus.FAIL, failed.status)
        self.assertNotIn("topsecret", failed.error_message)
        self.assertEqual(TestStatus.ERROR, errored.status)
        self.assertNotIn("topsecret", errored.error_message)

    def test_invalid_and_missing_environment_are_errors(self):
        case = TestCase("test_x", "X")
        invalid = self.executor.execute("def test_x(:\n pass", case, {})
        missing = self.executor.execute("def test_x():\n print('{{USERNAME}}')", case, {})
        self.assertEqual(TestStatus.ERROR, invalid.status)
        self.assertEqual(TestStatus.ERROR, missing.status)
        self.assertIn("Missing environment variable", missing.error_message)

    def test_unrelated_top_level_code_is_not_executed(self):
        source = "raise RuntimeError('should not run')\ndef test_safe():\n    assert True\n"
        result = self.executor.execute(source, parse_script(source).tests[0], {})
        self.assertEqual(TestStatus.PASS, result.status)

    def test_contract_blocks_direct_file_access_and_dynamic_imports(self):
        file_source = "def test_file():\n    open('private.txt')\n"
        import_source = "def test_import():\n    __import__('os')\n"
        file_result = self.executor.execute(file_source, parse_script(file_source).tests[0], {})
        import_result = self.executor.execute(import_source, parse_script(import_source).tests[0], {})
        self.assertEqual(TestStatus.ERROR, file_result.status)
        self.assertIn("NameError", file_result.error_message)
        self.assertEqual(TestStatus.ERROR, import_result.status)
        self.assertIn("Unsupported import", import_result.error_message)


class StoppingExecutor:
    def __init__(self, runner):
        self.runner, self.calls = runner, 0
    def execute(self, source, test, environment):
        self.calls += 1
        self.runner.stop()
        return ExecutionResult(TestStatus.PASS, 1)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "postbaby.db")
        self.project = self.db.create_project("Test API")
        self.source = "def test_one():\n assert True\ndef test_two():\n assert True\ndef test_three():\n assert True\n"
        self.tests = parse_script(self.source).tests

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def _session(self):
        return SessionManager(self.db).create_session(self.project.id, self.source, self.tests, {"BASE_URL": "https://safe.example", "TOKEN": "never-store"})

    def test_run_selected_persists_and_resume_skips_final_results(self):
        session = self._session()
        runner = TestRunner(self.db)
        outcomes = runner.run_selected(session.id, self.source, self.tests[:2], {})
        self.assertEqual(2, len(outcomes))
        self.assertEqual(2, self.db.get_session(session.id).completed_tests)
        self.assertEqual(["test_three"], [item.function_name for item in self.db.unfinished_tests(session.id)])
        resumed = runner.resume(session.id, self.source, {})
        self.assertEqual(1, len(resumed))
        self.assertEqual(SessionStatus.COMPLETE, self.db.get_session(session.id).status)
        self.assertEqual(self.source, self.db.latest_script_snapshot(session.id))

    def test_stop_pauses_and_does_not_start_new_tests(self):
        session = self._session()
        runner = TestRunner(self.db)
        runner.executor = StoppingExecutor(runner)
        outcomes = runner.run_all(session.id, self.source, self.tests, {})
        self.assertEqual(1, len(outcomes))
        self.assertEqual(SessionStatus.PAUSED, self.db.get_session(session.id).status)
        self.assertEqual(1, self.db.get_session(session.id).completed_tests)

    def test_results_survive_reopen_and_running_recovers(self):
        session = self._session()
        TestRunner(self.db).run_one(session.id, self.source, self.tests[0], {})
        self.db.set_session_status(session.id, SessionStatus.RUNNING)
        path = self.db.path
        self.db.close()
        reopened = Database(path)
        recovered = reopened.recover_interrupted_sessions()
        self.assertEqual([session.id], [item.id for item in recovered])
        self.assertEqual(SessionStatus.INTERRUPTED, reopened.get_session(session.id).status)
        reopened.close()
