import tempfile
import unittest
from pathlib import Path

from postbaby.controller import ApplicationController
from postbaby.database import Database


SOURCE = "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n"


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "postbaby.db")
        self.controller = ApplicationController(self.database)

    def tearDown(self):
        self.database.close(); self.temp.cleanup()

    def test_parse_populates_and_selects_tests(self):
        result = self.controller.state.parse(SOURCE)
        self.assertTrue(result.valid)
        self.assertEqual(["test_one", "test_two"], [test.function_name for test in self.controller.state.tests])
        self.controller.state.set_selected("test_two", False)
        self.assertEqual(["test_one"], [test.function_name for test in self.controller.state.selected_tests()])

    def test_start_session_uses_safe_environment_and_selected_tests(self):
        self.controller.state.parse(SOURCE)
        self.controller.state.set_selected("test_two", False)
        session, tests = self.controller.start_session("GUI API", {"BASE_URL": "https://example.test", "TOKEN": "do-not-save"}, selected_only=True)
        self.assertEqual(1, session.total_tests)
        self.assertEqual(["test_one"], [test.function_name for test in tests])
        metadata = self.database.connection.execute("SELECT environment_metadata FROM sessions WHERE id=?", (session.id,)).fetchone()[0]
        self.assertIn("https://example.test", metadata)
        self.assertNotIn("do-not-save", metadata)
