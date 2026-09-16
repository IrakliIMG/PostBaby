import tempfile
import unittest
from pathlib import Path

from postbaby.app import PostBabyApp, THEMES
from postbaby.database import Database
from postbaby.models import TestResult, TestStatus


class FinalVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "verification_postbaby.db"
        self.database = Database(self.db_path)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_complete_user_flow_verification(self):
        # 1. Start application
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()

        try:
            # 24. Verify pacifier icon appears in the application
            self.assertIsNotNone(app.pacifier_photo)
            self.assertTrue(Path("postbaby/pacifier.ico").exists())
            self.assertTrue(Path("pacifier.ico").exists())

            # 2. Create project
            app._create_and_open_new_project("Verification API")
            self.assertEqual("Verification API", app.project_name.get())

            # 3. Add Python script containing multiple test functions
            source = (
                "# TC-001\n"
                "# First Verification Test\n"
                "def test_one():\n"
                "    assert True\n"
                "\n"
                "# TC-002\n"
                "# Second Verification Test\n"
                "def test_two():\n"
                "    assert True\n"
                "\n"
                "# TC-003\n"
                "def test_three():\n"
                "    assert True\n"
            )
            app.editor.delete("1.0", "end")
            app.editor.insert("1.0", source)

            # 4. Confirm tests appear
            app.parse_script()
            self.assertEqual(3, len(app.controller.state.tests))
            self.assertEqual(["test_one", "test_two", "test_three"], [t.function_name for t in app.controller.state.tests])

            # 5. Select TC-001
            app._select_all(False)
            app.focused_function = "test_one"
            app._update_code_highlighting("test_one")

            # 6. Confirm corresponding function is highlighted
            focused_ranges = app.editor.tag_ranges("focused_test")
            self.assertTrue(len(focused_ranges) >= 2)
            self.assertEqual("1.0", str(focused_ranges[0]))

            # 7. Select TC-002
            app.controller.state.set_selected("test_two", True)
            app._update_code_highlighting("test_one")

            # 8. Confirm second function is highlighted differently
            selected_ranges = app.editor.tag_ranges("selected_test")
            self.assertTrue(len(selected_ranges) >= 2)
            self.assertEqual("6.0", str(selected_ranges[0]))

            # 9. Select both
            app.controller.state.set_selected("test_one", True)
            app.controller.state.set_selected("test_two", True)
            app._update_code_highlighting("test_one")

            # 10. Confirm both remain visually distinguishable
            focused_bg = app.editor.tag_cget("focused_test", "background")
            selected_bg = app.editor.tag_cget("selected_test", "background")
            self.assertNotEqual(focused_bg, selected_bg)

            # 11. Edit script
            app.editor.insert("1.0", "# Preamble header\nx = 100\n\n")

            # 12. Confirm mapping refreshes correctly
            app.parse_script()
            t1 = app.controller.state.tests[0]
            self.assertEqual(4, t1.start_line)
            app.focused_function = "test_one"
            app._update_code_highlighting("test_one")
            updated_focused = app.editor.tag_ranges("focused_test")
            self.assertEqual("4.0", str(updated_focused[0]))

            # 13. Toggle Dark Mode / Light Mode
            initial_theme = app.theme_mode
            app.toggle_theme()
            self.assertNotEqual(initial_theme, app.theme_mode)
            toggled_theme = app.theme_mode

            # 14. Navigate between screens
            app.show_welcome()
            self.assertEqual(toggled_theme, app.theme_mode)
            app.show_projects()
            self.assertEqual(toggled_theme, app.theme_mode)
            app.show_runner()
            self.assertEqual(toggled_theme, app.theme_mode)

            # 15. Confirm all UI remains consistent
            self.assertEqual(THEMES[toggled_theme]["editor_bg"], app.editor.cget("bg"))

            # 16. Toggle Light Mode explicitly
            app.set_theme("light")
            self.assertEqual("light", app.theme_mode)
            self.assertEqual("light", self.database.get_setting("theme"))
        finally:
            app._close(prompt=False)

        # 17. Restart application
        reopened = PostBabyApp(db_path=self.db_path)
        reopened.withdraw()
        try:
            # 18. Confirm theme persists
            self.assertEqual("light", reopened.theme_mode)

            # 19. Create multiple projects
            p1 = self.database.create_project("Project Alpha")
            p2 = self.database.create_project("Project Beta")

            # Add sessions and results to Project Alpha
            sess_a = self.database.create_session(p1.id, 1)
            self.database.save_test_result(TestResult(None, sess_a.id, "test_sample", TestStatus.PASS))

            self.assertEqual(3, len(self.database.list_projects()))  # Verification API + Alpha + Beta

            # 20. Delete one project
            deleted = self.database.delete_project(p1.id)
            self.assertTrue(deleted)

            # 21. Confirm only that project disappears
            current_projects = [p["name"] for p in self.database.list_projects()]
            self.assertNotIn("Project Alpha", current_projects)
            self.assertIn("Project Beta", current_projects)
            self.assertIn("Verification API", current_projects)

            # 22. Confirm its sessions/results are deleted
            sessions = self.database.connection.execute("SELECT * FROM sessions WHERE project_id=?", (p1.id,)).fetchall()
            self.assertEqual(0, len(sessions))
            results = self.database.connection.execute("SELECT * FROM test_results WHERE session_id=?", (sess_a.id,)).fetchall()
            self.assertEqual(0, len(results))

            # 23. Confirm other projects remain intact
            reopened.open_project(p2.id)
            self.assertEqual("Project Beta", reopened.project_name.get())
        finally:
            reopened._close(prompt=False)
