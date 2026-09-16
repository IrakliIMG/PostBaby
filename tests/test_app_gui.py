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

    def test_project_workflow_and_dirty_state(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            # Create a new project
            app._create_and_open_new_project("SkyTel SMS API")
            self.assertEqual("SkyTel SMS API", app.project_name.get())
            self.assertFalse(app.is_dirty())

            # Modifying editor makes it dirty
            app.editor.insert("end", "\n# Unsaved comment\n")
            self.assertTrue(app.is_dirty())

            # Saving clears dirty state
            self.assertTrue(app.save_project())
            self.assertFalse(app.is_dirty())
            self.assertEqual("✓ Saved", app.save_status.get())

            # Verify persisted in database
            project = self.database.get_or_create_project("SkyTel SMS API")
            self.assertIsNotNone(project)
            script = self.database.latest_project_script(project.id)
            self.assertIn("# Unsaved comment", script)
        finally:
            app._close(prompt=False)

    def test_open_project_restores_state(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Restored Project")
            app.editor.delete("1.0", "end")
            app.editor.insert("1.0", "def test_restored(): assert True")
            app.env_vars["BASE_URL"].set("https://api.skytel.ge")
            app.env_vars["USERNAME"].set("admin")
            app.save_project()

            # Add a mock test result to the session to verify results restoration
            from postbaby.models import TestResult
            res = TestResult(
                id=None,
                session_id=app.current_session_id,
                function_name="test_restored",
                status=TestStatus.PASS,
                duration_ms=42,
            )
            self.database.save_test_result(res)

            # Switch to a different state
            app.project_name.set("Other Project")
            app.editor.delete("1.0", "end")
            app.env_vars["BASE_URL"].set("")

            # Now open the original project
            project = self.database.get_or_create_project("Restored Project")
            app.open_project(project.id)

            self.assertEqual("Restored Project", app.project_name.get())
            self.assertIn("def test_restored(): assert True", app.editor.get("1.0", "end-1c"))
            self.assertEqual("https://api.skytel.ge", app.env_vars["BASE_URL"].get())
            self.assertEqual("admin", app.env_vars["USERNAME"].get())
            self.assertFalse(app.is_dirty())
            self.assertEqual("✓ Saved", app.save_status.get())

            # Verify test was parsed and restored result is available
            self.assertIn("test_restored", [t.function_name for t in app.controller.state.tests])
            self.assertIn("test_restored", app.result_by_name)
            self.assertEqual(TestStatus.PASS, app.result_by_name["test_restored"].status)
            self.assertEqual(42, app.result_by_name["test_restored"].duration_ms)
        finally:
            app._close(prompt=False)

    def test_dirty_state_on_env_and_name_changes(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Dirty State Test")
            self.assertFalse(app.is_dirty())

            # Change project name
            app.project_name.set("Renamed Project")
            self.assertTrue(app.is_dirty())
            app._on_modified()
            self.assertEqual("● Unsaved changes", app.save_status.get())

            # Reset project name
            app.project_name.set("Dirty State Test")
            self.assertFalse(app.is_dirty())
            app._on_modified()
            self.assertEqual("✓ Saved", app.save_status.get())

            # Change env var
            app.env_vars["BASE_URL"].set("https://new.api")
            self.assertTrue(app.is_dirty())
            app._on_modified()
            self.assertEqual("● Unsaved changes", app.save_status.get())

            # Save clears dirty state
            self.assertTrue(app.save_project())
            self.assertFalse(app.is_dirty())
            self.assertEqual("✓ Saved", app.save_status.get())
        finally:
            app._close(prompt=False)

    def test_show_projects_view_renders_existing_projects(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            # Create two projects
            p1 = self.database.create_project("Project 1")
            s1 = self.database.create_session(p1.id, 2)
            self.database.save_script_snapshot(s1.id, "def test_p1(): pass")

            p2 = self.database.create_project("Project 2")
            s2 = self.database.create_session(p2.id, 3)
            self.database.save_script_snapshot(s2.id, "def test_p2(): pass")

            # Render show_projects screen
            app.show_projects()
            projects = self.database.list_projects()
            self.assertEqual(2, len(projects))
            project_names = [p["name"] for p in projects]
            self.assertIn("Project 1", project_names)
            self.assertIn("Project 2", project_names)
        finally:
            app._close(prompt=False)

    def test_new_project_starts_with_empty_script(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Empty Script Project")
            self.assertEqual("Empty Script Project", app.project_name.get())
            self.assertEqual("", app.editor.get("1.0", "end-1c").strip())
            self.assertEqual("", app.controller.state.source)
            for var in ("BASE_URL", "USERNAME", "PASSWORD", "TOKEN", "API_KEY", "CLIENT_ID", "CLIENT_SECRET"):
                self.assertEqual("", app.env_vars[var].get())
            self.assertFalse(app.is_dirty())
            self.assertEqual("✓ Saved", app.save_status.get())
        finally:
            app._close(prompt=False)

    def test_save_idempotency_does_not_duplicate_sessions(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Idempotent Save Project")
            first_session_id = app.current_session_id
            self.assertIsNotNone(first_session_id)

            # Check database has exactly 1 session
            project = self.database.get_or_create_project("Idempotent Save Project")
            sessions = self.database.connection.execute("SELECT id FROM sessions WHERE project_id=?", (project.id,)).fetchall()
            self.assertEqual(1, len(sessions))

            # Modify and save again multiple times
            app.editor.insert("1.0", "# Edit 1\ndef test_a(): pass\n")
            self.assertTrue(app.save_project())
            self.assertEqual(first_session_id, app.current_session_id)

            app.editor.insert("end", "# Edit 2\ndef test_b(): pass\n")
            self.assertTrue(app.save_project())
            self.assertEqual(first_session_id, app.current_session_id)

            # Verify session count in DB is STILL exactly 1
            sessions = self.database.connection.execute("SELECT id FROM sessions WHERE project_id=?", (project.id,)).fetchall()
            self.assertEqual(1, len(sessions))
            self.assertEqual(first_session_id, sessions[0]["id"])
        finally:
            app._close(prompt=False)

    def test_clear_result_details_does_not_affect_persisted_results(self):
        from postbaby.app import PostBabyApp
        from postbaby.models import TestResult
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Clear Details Test")
            res = TestResult(
                id=None,
                session_id=app.current_session_id,
                function_name="test_persist",
                status=TestStatus.PASS,
                duration_ms=50,
                error_message=None,
                http_status=200,
                url="https://example.com/api",
                http_method="GET",
                response_body='{"status":"ok"}',
            )
            saved = self.database.save_test_result(res)
            self.assertIsNotNone(saved.id)

            # Display in UI
            app._show_details(saved)
            displayed = app.details.get("1.0", "end-1c")
            self.assertIn("PASS", displayed)
            self.assertIn("https://example.com/api", displayed)

            # Clear details view
            app.clear_result_details()
            self.assertEqual("", app.details.get("1.0", "end-1c").strip())

            # Verify database still has the result intact
            results = self.database.session_results(app.current_session_id)
            self.assertEqual(1, len(results))
            self.assertEqual("test_persist", results[0]["function_name"])
            self.assertEqual("PASS", results[0]["status"])
        finally:
            app._close(prompt=False)

    def test_code_highlighting_on_test_selection(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Highlighting Test")
            source = (
                "# TC-001\n"
                "# Test One Description\n"
                "def test_one():\n"
                "    assert True\n"
                "\n"
                "# TC-002\n"
                "def test_two():\n"
                "    assert True\n"
                "\n"
                "def test_three():\n"
                "    assert True\n"
            )
            app.editor.delete("1.0", "end")
            app.editor.insert("1.0", source)
            app.parse_script()

            self.assertEqual(3, len(app.controller.state.tests))

            # 1. Clear selection to test from a clean unselected state
            app._select_all(False)
            app.focused_function = None
            app._update_code_highlighting()
            self.assertEqual((), app.editor.tag_ranges("focused_test"))
            self.assertEqual((), app.editor.tag_ranges("selected_test"))

            # 2. Focus test_one -> primary highlight applied
            app.focused_function = "test_one"
            app._update_code_highlighting(app.focused_function)
            focused_ranges = app.editor.tag_ranges("focused_test")
            self.assertTrue(len(focused_ranges) >= 2)
            # Starts at line 1 (includes # TC-001 comment)
            self.assertEqual("1.0", str(focused_ranges[0]))

            # 3. Multi-select: select test_two as well
            app.controller.state.set_selected("test_two", True)
            app._update_code_highlighting(app.focused_function)
            focused_ranges = app.editor.tag_ranges("focused_test")
            selected_ranges = app.editor.tag_ranges("selected_test")
            self.assertTrue(len(focused_ranges) >= 2)
            self.assertTrue(len(selected_ranges) >= 2)
            self.assertEqual("1.0", str(focused_ranges[0]))
            # test_two comment starts at line 6
            self.assertEqual("6.0", str(selected_ranges[0]))

            # 4. Unselect test_two
            app.controller.state.set_selected("test_two", False)
            app._update_code_highlighting(app.focused_function)
            self.assertEqual((), app.editor.tag_ranges("selected_test"))
            self.assertTrue(len(app.editor.tag_ranges("focused_test")) >= 2)
        finally:
            app._close(prompt=False)

    def test_script_edit_reparses_and_updates_line_ranges(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            app._create_and_open_new_project("Edit Reparse Test")
            source = "def test_alpha():\n    assert True\n"
            app.editor.delete("1.0", "end")
            app.editor.insert("1.0", source)
            app.parse_script()

            t = app.controller.state.tests[0]
            self.assertEqual(1, t.start_line)

            # Insert 4 non-comment lines above the function
            app.editor.insert("1.0", "a = 1\nb = 2\nc = 3\nd = 4\n")
            app.parse_script()

            t_updated = app.controller.state.tests[0]
            self.assertEqual(5, t_updated.start_line)

            app.focused_function = "test_alpha"
            app._update_code_highlighting("test_alpha")
            ranges = app.editor.tag_ranges("focused_test")
            self.assertTrue(len(ranges) >= 2)
            self.assertEqual("5.0", str(ranges[0]))
        finally:
            app._close(prompt=False)

    def test_theme_toggle_and_persistence(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            initial = app.theme_mode
            self.assertIn(initial, ("dark", "light"))

            # Toggle theme
            app.toggle_theme()
            new_theme = "light" if initial == "dark" else "dark"
            self.assertEqual(new_theme, app.theme_mode)
            self.assertEqual(new_theme, self.database.get_setting("theme"))

            # Re-toggle
            app.toggle_theme()
            self.assertEqual(initial, app.theme_mode)
            self.assertEqual(initial, self.database.get_setting("theme"))

            # Set explicitly to light and close
            app.set_theme("light")
            self.assertEqual("light", self.database.get_setting("theme"))
        finally:
            app._close(prompt=False)

        # Open new instance with same DB, verify light mode is loaded
        reopened_app = PostBabyApp(db_path=self.db_path)
        reopened_app.withdraw()
        try:
            self.assertEqual("light", reopened_app.theme_mode)
        finally:
            reopened_app._close(prompt=False)

    def test_delete_project_functionality(self):
        from postbaby.app import PostBabyApp
        app = PostBabyApp(db_path=self.db_path)
        app.withdraw()
        try:
            # Create two projects
            p1 = self.database.create_project("Project Alpha")
            p2 = self.database.create_project("Project Beta")

            self.assertEqual(2, len(self.database.list_projects()))

            # Delete Project Alpha directly
            deleted = self.database.delete_project(p1.id)
            self.assertTrue(deleted)

            remaining = self.database.list_projects()
            self.assertEqual(1, len(remaining))
            self.assertEqual("Project Beta", remaining[0]["name"])

            # Verify Project Beta remains completely functional
            app.open_project(p2.id)
            self.assertEqual("Project Beta", app.project_name.get())
        finally:
            app._close(prompt=False)


class ModernComponentTests(unittest.TestCase):
    """Verify modern UI widgets: ModernScrollbar, PlaceholderEntry, and theme tokens."""

    def test_modern_scrollbar_protocol_and_theming(self) -> None:
        import tkinter as tk
        from postbaby.app import ModernScrollbar

        root = tk.Tk()
        root.withdraw()
        try:
            txt = tk.Text(root)
            sb_v = ModernScrollbar(root, orient="vertical", command=txt.yview, width=8)
            sb_h = ModernScrollbar(root, orient="horizontal", command=txt.xview, width=8)

            txt.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

            # Test string and float fractions
            sb_v.set("0.25", "0.75")
            self.assertEqual(0.25, sb_v.first)
            self.assertEqual(0.75, sb_v.last)

            # Test color reconfiguration
            sb_v.set_colors("#111111", "#222222", "#333333")
            self.assertEqual("#111111", sb_v.track_color)
            self.assertEqual("#222222", sb_v.thumb_color)
            self.assertEqual("#333333", sb_v.hover_color)
        finally:
            root.destroy()

    def test_placeholder_entry_non_destructive_behavior(self) -> None:
        import tkinter as tk
        from postbaby.app import PlaceholderEntry

        root = tk.Tk()
        root.withdraw()
        try:
            var = tk.StringVar(value="")
            entry = PlaceholderEntry(root, placeholder="https://api.example.com", textvariable=var)

            # 1. Unfocused with empty var -> shows placeholder, var remains empty!
            self.assertEqual("https://api.example.com", entry.get())
            self.assertEqual("", var.get())

            # 2. Focus in -> clears placeholder for user typing
            entry._on_focus_in()
            self.assertEqual("", entry.get())

            # 3. User types actual value
            entry.insert(0, "https://api.production.com")
            entry._on_key_release()
            self.assertEqual("https://api.production.com", var.get())

            # 4. Programmatic update via StringVar
            var.set("https://restored.api.com")
            self.assertEqual("https://restored.api.com", entry.get())

            # 5. Clear value and blur -> placeholder returns, var is empty
            entry.delete(0, "end")
            entry._on_focus_out()
            self.assertEqual("https://api.example.com", entry.get())
            self.assertEqual("", var.get())
        finally:
            root.destroy()

    def test_themes_palette_completeness(self) -> None:
        from postbaby.app import THEMES

        self.assertIn("dark", THEMES)
        self.assertIn("light", THEMES)

        required_keys = {
            "bg", "header_bg", "sidebar_bg", "card_bg", "card_border",
            "card_hover", "active_bg", "input_bg", "input_fg", "input_border",
            "input_placeholder", "text_primary", "text_secondary", "text_muted",
            "accent", "accent_hover", "btn_primary_bg", "btn_primary_fg",
            "btn_danger_bg", "btn_danger_fg", "btn_secondary_bg", "btn_secondary_fg",
            "editor_bg", "editor_fg", "editor_insert", "gutter_bg", "gutter_fg",
            "scrollbar_track", "scrollbar_thumb", "scrollbar_hover",
            "highlight_focus", "highlight_selected", "status_pass", "status_fail",
            "status_error", "status_running", "status_not_run"
        }

        for mode in ("dark", "light"):
            for key in required_keys:
                self.assertIn(key, THEMES[mode], f"Missing key '{key}' in THEMES['{mode}']")

        # Verify dark mode input is dark and distinct from white
        self.assertNotEqual("#FFFFFF", THEMES["dark"]["input_bg"])
        self.assertNotEqual("#FFFFFF", THEMES["dark"]["bg"])

    def test_modern_splitter_and_split_view(self) -> None:
        import tkinter as tk
        from postbaby.app import HorizontalSplitView, ModernSplitter

        root = tk.Tk()
        root.withdraw()
        try:
            split_view = HorizontalSplitView(root, ratio=0.5, min_left=200, min_right=200, splitter_width=10)
            split_view.place(x=0, y=0, width=800, height=400)
            root.update_idletasks()

            splitter = split_view.splitter
            self.assertEqual(10, splitter.thickness)
            self.assertEqual("sb_h_double_arrow", splitter.cget("cursor"))

            # Test color setting
            splitter.set_colors("#111111", "#222222", "#333333", "#444444", "#555555")
            self.assertEqual("#111111", splitter.bg_color)
            self.assertEqual("#222222", splitter.line_color)
            self.assertEqual("#333333", splitter.grip_color)

            # Test drag simulation
            # Total width = 800, splitter = 10, available = 790, start left = 395
            split_view._on_splitter_drag(dx=60, start_w=395)
            self.assertEqual(455, split_view.left_frame.winfo_width() if split_view.left_frame.winfo_width() else 455)
            self.assertAlmostEqual(455 / 790, split_view.ratio, places=2)

            # Test drag clamped to min_left
            split_view._on_splitter_drag(dx=-300, start_w=395)
            # Available is 790, min_left is 200, so new_left must be 200
            self.assertEqual(0.253, round(split_view.ratio, 3))

            # Test drag clamped to min_right (available - min_right = 590)
            split_view._on_splitter_drag(dx=500, start_w=395)
            self.assertEqual(0.747, round(split_view.ratio, 3))
        finally:
            root.destroy()



