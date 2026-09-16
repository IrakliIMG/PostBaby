"""Visual acceptance tests for modern UI polish pass."""

import tempfile
import unittest
from pathlib import Path

from postbaby.app import PostBabyApp, THEMES
from postbaby.models import TestResult, TestStatus


class VisualAcceptanceTests(unittest.TestCase):
    def test_visual_and_theming_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "vis_test.db"
            app = PostBabyApp(db_path=db)
            app.withdraw()

            try:
                # 1. Dark mode checks
                app.set_theme("dark")
                self.assertEqual(THEMES["dark"]["bg"], app.cget("bg"))

                # 2. Open project / show runner
                app._create_and_open_new_project("Visual Polish Test")
                self.assertEqual("Visual Polish Test", app.project_name.get())

                # 3. Check environment inputs
                self.assertTrue(hasattr(app, "placeholder_entries"))
                self.assertEqual(7, len(app.placeholder_entries))
                for pe in app.placeholder_entries:
                    self.assertEqual(THEMES["dark"]["input_fg"], pe.normal_fg)
                    self.assertEqual(THEMES["dark"]["input_placeholder"], pe.placeholder_fg)

                # 4. Check modern scrollbars
                self.assertTrue(hasattr(app, "editor_yscroll"))
                self.assertTrue(hasattr(app, "editor_xscroll"))
                self.assertTrue(hasattr(app, "tree_scroll"))
                self.assertTrue(hasattr(app, "detail_scroll"))
                self.assertEqual(8, app.editor_yscroll.thickness)
                self.assertEqual(8, app.tree_scroll.thickness)
                self.assertEqual(8, app.detail_scroll.thickness)

                # 5. Check treeview columns
                cols = app.tree.cget("columns")
                self.assertEqual(("check", "id", "name", "status", "duration"), tuple(cols))

                # 6. Parse and render tests
                source = "# TC-VIS-001\n# Visual Test 1\ndef test_first():\n    assert True\n\n# TC-VIS-002\n# Visual Test 2\ndef test_second():\n    assert True\n"
                app.editor.insert("1.0", source)
                app.parse_script()
                self.assertEqual(2, len(app.tree.get_children()))
                row1 = app.tree.item("test_first", "values")
                self.assertEqual("TC-VIS-001", row1[1])
                self.assertEqual("Visual Test 1", row1[2])

                # 7. Check result details formatting
                res = TestResult(
                    id=None,
                    session_id=app.current_session_id,
                    function_name="test_first",
                    status=TestStatus.PASS,
                    duration_ms=25,
                    test_id="TC-VIS-001",
                    error_message=None,
                    http_status=200,
                )
                # Attach request/response metadata
                object.__setattr__(res, "url", "https://api.example.com/health")
                object.__setattr__(res, "http_method", "GET")
                object.__setattr__(res, "response_body", '{"ok":true}')

                app._show_details(res)
                details_text = app.details.get("1.0", "end")
                self.assertIn("STATUS:", details_text)
                self.assertIn("DURATION:", details_text)
                self.assertIn("REQUEST", details_text)
                self.assertIn("RESPONSE", details_text)
                self.assertIn("https://api.example.com/health", details_text)

                # Save project so dirty state is cleared
                self.assertTrue(app.save_project())

                # 8. Check light mode switch
                app.toggle_theme()
                self.assertEqual("light", app.theme_mode)
                self.assertEqual(THEMES["light"]["bg"], app.cget("bg"))
                self.assertEqual(THEMES["light"]["editor_bg"], app.editor.cget("bg"))
                for pe in app.placeholder_entries:
                    self.assertEqual(THEMES["light"]["input_fg"], pe.normal_fg)
                    self.assertEqual(THEMES["light"]["input_placeholder"], pe.placeholder_fg)

                # 9. Check projects screen
                app.show_projects(prompt=False)
                self.assertTrue(hasattr(app, "projects_scrollbar"))
                self.assertEqual(8, app.projects_scrollbar.thickness)

                # 10. Check welcome screen
                app.show_welcome()
            finally:
                app._close(prompt=False)


if __name__ == "__main__":
    unittest.main()
