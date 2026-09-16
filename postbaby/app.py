"""Tkinter desktop application for the PostBaby execution core."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .controller import ApplicationController
from .database import Database
from .llm_message import LLM_MESSAGE
from .models import SessionStatus, TestStatus
from .runner import TestRunner
from .report import ReportGenerator
from .paths import default_database_path

STATUS_MARK = {"PASS": "✓ PASS", "FAIL": "✗ FAIL", "ERROR": "⚠ ERROR", "RUNNING": "⏱ RUNNING", "NOT_RUN": "○ NOT RUN", "SKIPPED": "– SKIPPED", "INTERRUPTED": "⚠ INTERRUPTED"}


class PostBabyApp(tk.Tk):
    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("PostBaby 🍼")
        self.geometry("1140x800")
        self.minsize(880, 640)
        self._setup_styles()

        self.database = Database(db_path or default_database_path())
        self.controller = ApplicationController(self.database)
        self.runner = TestRunner(self.database)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.result_by_name: dict[str, Any] = {}
        self.current_session_id: int | None = None
        self.resume_session_id: int | None = None
        self.running = False
        self.env_vars = {
            key: tk.StringVar()
            for key in ("BASE_URL", "USERNAME", "PASSWORD", "TOKEN", "API_KEY", "CLIENT_ID", "CLIENT_SECRET")
        }
        self.project_name = tk.StringVar(value="My API Project")
        self.save_status = tk.StringVar(value="✓ Saved")
        self.status = tk.StringVar(value="● Ready")
        self.progress = tk.StringVar(value="No tests parsed")
        self._saved_project_name = "My API Project"
        self._saved_source = ""
        self._saved_env = {k: "" for k in self.env_vars}
        self._menu()
        self.show_welcome()
        interrupted = self.database.recover_interrupted_sessions()
        if interrupted:
            self.after(150, lambda: self.show_recovery(interrupted))
        self._drain_job = self.after(80, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=("Segoe UI", 9))
        style.configure("TLabel", font=("Segoe UI", 9))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Brand.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#64748B")
        style.configure("Required.TLabel", font=("Segoe UI", 9, "bold"), foreground="#0F172A")
        style.configure("Saved.TLabel", font=("Segoe UI", 9, "bold"), foreground="#16A34A")
        style.configure("Unsaved.TLabel", font=("Segoe UI", 9, "bold"), foreground="#D97706")

        style.configure("TButton", font=("Segoe UI", 9), padding=(8, 4))
        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), padding=(10, 5))
        style.configure("Danger.TButton", font=("Segoe UI", 9), padding=(8, 4))

        style.configure("TLabelframe", padding=8)
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"), foreground="#334155")

        style.configure("Treeview", font=("Segoe UI", 9), rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(4, 4))
        style.configure("TProgressbar", thickness=8)

    def _menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Project...", command=self.prompt_new_project)
        file_menu.add_command(label="Open Project...", command=self.show_projects)
        file_menu.add_command(label="Save Project", command=self.save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Session History", command=self.show_history)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Validate Script", command=self.parse_script)
        tools.add_command(label="Copy Script Contract", command=self.copy_llm_message)
        menu.add_cascade(label="File", menu=file_menu)
        menu.add_cascade(label="Tools", menu=tools)
        self.config(menu=menu)

    def _clear(self) -> None:
        if hasattr(self, "editor"):
            delattr(self, "editor")
        for child in self.winfo_children():
            child.destroy()

    def _mark_clean(self) -> None:
        self._saved_project_name = self.project_name.get()
        self._saved_source = self.editor.get("1.0", "end-1c") if hasattr(self, "editor") else self.controller.state.source
        self._saved_env = {k: v.get() for k, v in self.env_vars.items()}
        self.save_status.set("✓ Saved")

    def is_dirty(self) -> bool:
        if not hasattr(self, "editor"):
            return False
        current_source = self.editor.get("1.0", "end-1c")
        if current_source != getattr(self, "_saved_source", ""):
            return True
        if self.project_name.get() != getattr(self, "_saved_project_name", ""):
            return True
        current_env = {k: v.get() for k, v in self.env_vars.items()}
        if current_env != getattr(self, "_saved_env", {}):
            return True
        return False

    def _on_modified(self, *args) -> None:
        if self.is_dirty():
            self.save_status.set("● Unsaved changes")
        else:
            self.save_status.set("✓ Saved")

    def _on_text_modified(self, event=None) -> None:
        if hasattr(self, "editor") and self.editor.edit_modified():
            self._on_modified()
            self.editor.edit_modified(False)

    def save_project(self) -> bool:
        name = self.project_name.get().strip()
        if not name:
            messagebox.showerror("Invalid Project Name", "Project name cannot be empty.", parent=self)
            return False
        source = self.editor.get("1.0", "end-1c") if hasattr(self, "editor") else self.controller.state.source
        self.controller.state.source = source
        self.controller.state.parse(source)
        env = self._environment()
        try:
            project, session = self.controller.save_project(name, env, self.current_session_id)
            self.current_session_id = session.id
            self._mark_clean()
            self.save_status.set("✓ Saved")
            self.status.set(f"✓ Saved: {name}")
            return True
        except Exception as err:
            messagebox.showerror("Save Failed", f"Could not save project: {err}", parent=self)
            return False

    def go_back(self) -> None:
        if self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
                self.show_welcome()
            elif choice == "discard":
                if hasattr(self, "_saved_source"):
                    self.controller.state.source = self._saved_source
                self.show_welcome()
            elif choice == "cancel":
                return
        else:
            if hasattr(self, "editor"):
                self.controller.state.source = self.editor.get("1.0", "end-1c")
            self.show_welcome()

    def _prompt_unsaved_changes(self) -> str:
        dlg = tk.Toplevel(self)
        dlg.title("Unsaved Changes")
        dlg.geometry("400x145")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        choice = ["cancel"]

        def on_action(action: str) -> None:
            choice[0] = action
            dlg.destroy()

        content = ttk.Frame(dlg, padding=(24, 20, 24, 20))
        content.pack(fill="both", expand=True)

        ttk.Label(content, text="You have unsaved changes.", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(content, text="Save before returning to the welcome screen?", font=("Segoe UI", 9), foreground="#64748B").pack(anchor="w", pady=(0, 16))

        btn_box = ttk.Frame(content)
        btn_box.pack(fill="x")

        ttk.Button(btn_box, text="Save & Back", command=lambda: on_action("save")).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Cancel", command=lambda: on_action("cancel")).pack(side="right", padx=6)
        ttk.Button(btn_box, text="Discard", command=lambda: on_action("discard")).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", lambda: on_action("cancel"))
        self.wait_window(dlg)
        return choice[0]

    def prompt_new_project(self) -> None:
        if hasattr(self, "editor") and self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
            elif choice == "cancel":
                return

        dlg = tk.Toplevel(self)
        dlg.title("New Project")
        dlg.geometry("400x155")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        content = ttk.Frame(dlg, padding=(24, 20, 24, 20))
        content.pack(fill="both", expand=True)

        ttk.Label(content, text="Project Name", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        name_var = tk.StringVar(value="")
        entry = ttk.Entry(content, textvariable=name_var, font=("Segoe UI", 10))
        entry.pack(fill="x", pady=(6, 16))
        entry.focus_set()

        def create() -> None:
            val = name_var.get().strip()
            if not val:
                messagebox.showerror("Invalid Name", "Please enter a project name.", parent=dlg)
                return
            dlg.destroy()
            self._create_and_open_new_project(val)

        btn_box = ttk.Frame(content)
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="Create Project", command=create).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Cancel", command=dlg.destroy).pack(side="right")

        entry.bind("<Return>", lambda _: create())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        self.wait_window(dlg)

    def _create_and_open_new_project(self, name: str) -> None:
        project = self.database.get_or_create_project(name)
        self.project_name.set(project.name)
        for key in self.env_vars:
            self.env_vars[key].set("")
        self.current_session_id = None
        self.resume_session_id = None
        self.result_by_name.clear()

        # New projects start with empty script and clean save state
        self.controller.state.source = ""
        self.controller.state.tests = []
        self.controller.state.selected = set()

        self.show_runner()
        self.save_project()
        self._mark_clean()
        self.save_status.set("✓ Saved")
        self.status.set(f"● Project: {project.name}")

    def new_project(self) -> None:
        self.prompt_new_project()

    def show_projects(self) -> None:
        if hasattr(self, "editor") and self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
            elif choice == "cancel":
                return
        self._clear()

        root = ttk.Frame(self, padding=24)
        root.pack(fill="both", expand=True)

        top_bar = ttk.Frame(root)
        top_bar.pack(fill="x", pady=(0, 16))
        ttk.Button(top_bar, text="← Back", command=self.show_welcome).pack(side="left")
        ttk.Label(top_bar, text="📁 My Projects", font=("Segoe UI", 15, "bold")).pack(side="left", padx=(14, 0))
        ttk.Button(top_bar, text="✨ New Project", command=self.prompt_new_project).pack(side="right")

        projects = self.database.list_projects()

        if not projects:
            empty_box = ttk.Frame(root, padding=40)
            empty_box.pack(expand=True)
            ttk.Label(empty_box, text="No projects found.", font=("Segoe UI", 12, "italic"), foreground="#64748B").pack(pady=(0, 12))
            ttk.Button(empty_box, text="✨ Create First Project", command=self.prompt_new_project).pack()
            return

        canvas = tk.Canvas(root, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        list_frame = ttk.Frame(canvas)

        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for p in projects:
            pid = p["id"]
            name = p["name"]
            raw_time = p["last_modified"] or ""
            fmt_time = raw_time[:19].replace("T", " ") if raw_time else "Never"
            session_count = p["session_count"]

            card = ttk.LabelFrame(list_frame, padding=(16, 12))
            card.pack(fill="x", expand=True, pady=4, padx=4)

            left_card = ttk.Frame(card)
            left_card.pack(side="left", fill="both", expand=True)

            ttk.Label(left_card, text=name, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            info_text = f"Last modified: {fmt_time}"
            if session_count:
                info_text += f"   •   {session_count} session{'s' if session_count != 1 else ''}"
            ttk.Label(left_card, text=info_text, font=("Segoe UI", 9), foreground="#64748B").pack(anchor="w", pady=(3, 0))

            right_card = ttk.Frame(card)
            right_card.pack(side="right", padx=(12, 0))
            ttk.Button(right_card, text="Open", command=lambda p_id=pid: self.open_project(p_id)).pack(side="right")

    def open_project(self, project_id: int) -> None:
        p_row = self.database.connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not p_row:
            return
        self.project_name.set(p_row["name"])

        for k in self.env_vars:
            self.env_vars[k].set("")

        raw_meta = self.database.latest_project_environment(project_id)
        if raw_meta:
            try:
                import json
                meta = json.loads(raw_meta)
                for k in ("BASE_URL", "USERNAME", "CLIENT_ID"):
                    if k in meta:
                        self.env_vars[k].set(meta[k])
            except Exception:
                pass

        source = self.database.latest_project_script(project_id)
        self.controller.state.source = source if source is not None else ""

        latest_session = self.database.latest_project_session(project_id)
        self.resume_session_id = None
        self.show_runner()

        self.result_by_name.clear()
        if latest_session:
            self.current_session_id = latest_session.id
            for row in self.database.session_results(latest_session.id):
                self.result_by_name[row["function_name"]] = type("Result", (), dict(row))()
        else:
            self.current_session_id = None

        self._render_tests()
        self._mark_clean()
        self.save_status.set("✓ Saved")
        self.status.set(f"✓ Opened: {p_row['name']}")

    def show_welcome(self) -> None:
        self._clear()
        panel = ttk.Frame(self, padding=40)
        panel.place(relx=.5, rely=.46, anchor="center")

        ttk.Label(panel, text="🍼", font=("Segoe UI Emoji", 40)).pack()
        ttk.Label(panel, text="POSTBABY", font=("Segoe UI", 24, "bold")).pack(pady=(6, 2))
        ttk.Label(panel, text="Lightweight API Test Runner", font=("Segoe UI", 11), foreground="#64748B").pack(pady=(0, 24))

        has_projects = bool(self.database.list_projects())
        btn_box = ttk.Frame(panel)
        btn_box.pack(fill="x")

        ttk.Button(btn_box, text="✨  New Project", command=self.prompt_new_project, width=28).pack(pady=4)
        if has_projects:
            ttk.Button(btn_box, text="📁  Open Existing Project", command=self.show_projects, width=28).pack(pady=4)
        ttk.Button(btn_box, text="📋  Copy Script Contract", command=self.copy_llm_message, width=28).pack(pady=4)

    def show_runner(self) -> None:
        self._clear()
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # ── Header ──────────────────────────────────────────────────────────
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 8))

        left_header = ttk.Frame(header)
        left_header.pack(side="left")
        ttk.Button(left_header, text="← Back", command=self.go_back).pack(side="left", padx=(0, 10))
        ttk.Label(left_header, text="Project:", font=("Segoe UI", 10, "bold"), foreground="#475569").pack(side="left", padx=(0, 6))
        ttk.Label(left_header, textvariable=self.project_name, font=("Segoe UI", 12, "bold"), foreground="#0284C7").pack(side="left")

        right_header = ttk.Frame(header)
        right_header.pack(side="right")
        ttk.Label(right_header, textvariable=self.save_status, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))
        ttk.Button(right_header, text="💾 Save", command=self.save_project).pack(side="left", padx=(0, 6))
        ttk.Button(right_header, text="📋 Copy Contract", command=self.copy_llm_message).pack(side="left", padx=(0, 10))
        ttk.Label(right_header, textvariable=self.status, font=("Segoe UI", 9), foreground="#64748B").pack(side="left")

        # ── Environment Section ─────────────────────────────────────────────
        env = ttk.LabelFrame(root, text=" Environment ", padding=10)
        env.pack(fill="x", pady=(0, 6))

        base_frame = ttk.Frame(env)
        base_frame.pack(fill="x", pady=(0, 4))
        ttk.Label(base_frame, text="Base URL *", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Entry(base_frame, textvariable=self.env_vars["BASE_URL"]).pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Label(base_frame, text="* Only Base URL is required", font=("Segoe UI", 8, "italic"), foreground="#64748B").pack(side="left")

        opts_grid = ttk.Frame(env)
        opts_grid.pack(fill="x")

        ttk.Label(opts_grid, text="Token").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["TOKEN"], show="•", width=28).grid(row=0, column=1, sticky="ew", padx=(6, 16), pady=2)
        ttk.Label(opts_grid, text="API Key").grid(row=0, column=2, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["API_KEY"], show="•", width=28).grid(row=0, column=3, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(opts_grid, text="Username").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["USERNAME"], width=28).grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=2)
        ttk.Label(opts_grid, text="Password").grid(row=1, column=2, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["PASSWORD"], show="•", width=28).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(opts_grid, text="Client ID").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["CLIENT_ID"], width=28).grid(row=2, column=1, sticky="ew", padx=(6, 16), pady=2)
        ttk.Label(opts_grid, text="Client Secret").grid(row=2, column=2, sticky="w", pady=2)
        ttk.Entry(opts_grid, textvariable=self.env_vars["CLIENT_SECRET"], show="•", width=28).grid(row=2, column=3, sticky="ew", padx=(6, 0), pady=2)

        opts_grid.columnconfigure(1, weight=1)
        opts_grid.columnconfigure(3, weight=1)

        # ── Main Resizable Workspace ────────────────────────────────────────
        vpanes = ttk.PanedWindow(root, orient="vertical")
        vpanes.pack(fill="both", expand=True, pady=4)

        hpanes = ttk.PanedWindow(vpanes, orient="horizontal")
        vpanes.add(hpanes, weight=3)

        # Left: Python Test Script
        script_box = ttk.LabelFrame(hpanes, text=" Python Test Script ", padding=6)
        hpanes.add(script_box, weight=1)

        editor_frame = ttk.Frame(script_box)
        editor_frame.pack(fill="both", expand=True)

        self.editor = tk.Text(editor_frame, height=12, wrap="none", font=("Consolas", 10), undo=True)
        yscroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self.editor.yview)
        xscroll = ttk.Scrollbar(editor_frame, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.editor.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        editor_frame.columnconfigure(0, weight=1)
        editor_frame.rowconfigure(0, weight=1)

        script_actions = ttk.Frame(script_box)
        script_actions.pack(fill="x", pady=(6, 0))
        self.parse_button = ttk.Button(script_actions, text="Parse Tests", command=self.parse_script)
        self.parse_button.pack(side="left")
        ttk.Button(script_actions, text="Clear", command=lambda: self.editor.delete("1.0", "end")).pack(side="left", padx=6)

        if self.controller.state.source:
            self.editor.insert("1.0", self.controller.state.source)

        self._mark_clean()
        self.editor.bind("<KeyRelease>", lambda _: self._on_modified())
        self.editor.bind("<<Modified>>", self._on_text_modified)

        # Right: Test Cases
        cases_box = ttk.LabelFrame(hpanes, text=" Test Cases ", padding=6)
        hpanes.add(cases_box, weight=1)

        run_controls = ttk.Frame(cases_box)
        run_controls.pack(fill="x", pady=(0, 4))
        self.run_selected_button = ttk.Button(run_controls, text="▶ Run Selected", command=lambda: self.start_run(True))
        self.run_selected_button.pack(side="left", padx=(0, 4))
        self.run_all_button = ttk.Button(run_controls, text="▶ Run All", command=lambda: self.start_run(False))
        self.run_all_button.pack(side="left", padx=4)
        self.stop_button = ttk.Button(run_controls, text="■ Stop", command=self.stop_run, state="disabled")
        self.stop_button.pack(side="left", padx=4)

        select_controls = ttk.Frame(cases_box)
        select_controls.pack(fill="x", pady=(2, 4))
        ttk.Button(select_controls, text="Select All", command=lambda: self._select_all(True)).pack(side="left")
        ttk.Button(select_controls, text="Clear Selection", command=lambda: self._select_all(False)).pack(side="left", padx=4)

        self.tree = ttk.Treeview(cases_box, columns=("test", "status", "duration"), show="headings", selectmode="browse")
        for col, title, width in (("test", "Test", 260), ("status", "Status", 110), ("duration", "Duration", 70)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(2, 4))
        self.tree.bind("<ButtonRelease-1>", self._toggle_or_details)

        self.tree.tag_configure("PASS", foreground="#16A34A")
        self.tree.tag_configure("FAIL", foreground="#DC2626")
        self.tree.tag_configure("ERROR", foreground="#D97706")
        self.tree.tag_configure("RUNNING", foreground="#2563EB")
        self.tree.tag_configure("NOT_RUN", foreground="#64748B")

        progress_box = ttk.Frame(cases_box)
        progress_box.pack(fill="x", pady=(2, 0))
        self.bar = ttk.Progressbar(progress_box, mode="determinate")
        self.bar.pack(fill="x", pady=(0, 2))
        ttk.Label(progress_box, textvariable=self.progress, font=("Segoe UI", 8), foreground="#64748B").pack(anchor="w")

        # Bottom: Result Detail
        results_box = ttk.LabelFrame(vpanes, text=" Result Detail ", padding=6)
        vpanes.add(results_box, weight=2)

        results_header = ttk.Frame(results_box)
        results_header.pack(fill="x", pady=(0, 4))
        ttk.Label(results_header, text="Inspection & Assertions", font=("Segoe UI", 9, "bold"), foreground="#475569").pack(side="left")
        ttk.Button(results_header, text="Clear", command=self.clear_result_details).pack(side="right")

        detail_frame = ttk.Frame(results_box)
        detail_frame.pack(fill="both", expand=True)
        self.details = tk.Text(detail_frame, wrap="word", font=("Consolas", 10), state="disabled")
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.details.yview)
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

        self.details.tag_configure("badge_pass", font=("Segoe UI", 9, "bold"), foreground="#16A34A")
        self.details.tag_configure("badge_fail", font=("Segoe UI", 9, "bold"), foreground="#DC2626")
        self.details.tag_configure("badge_error", font=("Segoe UI", 9, "bold"), foreground="#D97706")
        self.details.tag_configure("section", font=("Segoe UI", 9, "bold"), foreground="#334155")
        self.details.tag_configure("key", font=("Segoe UI", 9, "bold"), foreground="#64748B")
        self.details.tag_configure("code", font=("Consolas", 10), foreground="#0F172A")
        self.details.tag_configure("error_code", font=("Consolas", 10), foreground="#DC2626")

        # ── Footer ──────────────────────────────────────────────────────────
        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(6, 0))
        self.summary = tk.StringVar(value="0 Tests  •  0 PASS  •  0 FAIL  •  0 ERROR")
        ttk.Label(footer, textvariable=self.summary, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(footer, text="📋 Copy Contract", command=self.copy_llm_message).pack(side="right")
        ttk.Button(footer, text="Session History", command=self.show_history).pack(side="right", padx=5)
        ttk.Button(footer, text="Export CSV", command=lambda: self.export_report("csv")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export JSON", command=lambda: self.export_report("json")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export HTML", command=lambda: self.export_report("html")).pack(side="right", padx=3)

        self.parse_script()

    def parse_script(self, clear_results: bool = True) -> None:
        source = self.editor.get("1.0", "end-1c") if hasattr(self, "editor") else self.controller.state.source
        if not source.strip():
            self.controller.state.tests = []
            self.controller.state.selected = set()
            if clear_results:
                self.result_by_name.clear()
            self._render_tests()
            self.status.set("● Ready")
            return

        result = self.controller.state.parse(source)
        if clear_results:
            self.result_by_name.clear()
        self._render_tests()
        if result.valid:
            self.status.set(f"✓ Script valid — {len(result.parse_result.tests)} test cases")
            if result.warnings:
                messagebox.showwarning("Script warnings", "\n".join(result.warnings), parent=self)
        else:
            self.status.set("✗ Script validation failed")
            if hasattr(self, "editor"):
                messagebox.showerror("PostBaby could not validate this script.", "\n".join(result.errors), parent=self)

    def _render_tests(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for test in self.controller.state.tests:
            result = self.result_by_name.get(test.function_name)
            selected = "☑" if test.function_name in self.controller.state.selected else "☐"
            title = f"{selected} {test.test_id or ''} {test.display_name}".strip()
            status_key = str(result.status) if result else "NOT_RUN"
            status = STATUS_MARK.get(status_key, status_key)
            duration = f"{result.duration_ms} ms" if result and result.duration_ms is not None else ""
            self.tree.insert("", "end", iid=test.function_name, values=(title, status, duration), tags=(status_key,))
        self._update_summary()

    def _toggle_or_details(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if self.tree.identify_column(event.x) == "#1":
            self.controller.state.set_selected(item, item not in self.controller.state.selected)
            self._render_tests()
        result = self.result_by_name.get(item)
        if result:
            self._show_details(result)

    def _select_all(self, selected: bool) -> None:
        self.controller.state.selected = {t.function_name for t in self.controller.state.tests} if selected else set()
        self._render_tests()

    def _environment(self) -> dict[str, str]:
        return {name: value.get() for name, value in self.env_vars.items()}

    def start_run(self, selected_only: bool) -> None:
        if not self.controller.state.tests:
            self.parse_script()
        if not self.controller.state.tests:
            return
        environment = self._environment()
        if not environment.get("BASE_URL", "").strip():
            messagebox.showerror(
                "Missing Base URL",
                "Base URL is required before running tests.\n\nPlease enter a Base URL in the Environment section.",
                parent=self,
            )
            return
        try:
            if self.resume_session_id:
                session = self.database.get_session(self.resume_session_id)
                tests = self.database.unfinished_tests(session.id)
            else:
                session, tests = self.controller.start_session(self.project_name.get(), environment, selected_only)
        except ValueError as error:
            messagebox.showerror("Cannot start run", str(error), parent=self)
            return

        self.current_session_id, self.running = session.id, True
        self.bar.configure(maximum=len(tests), value=0)
        self.progress.set(f"Running tests… 0 / {len(tests)}")
        self.status.set("⏱ Running")
        self._set_running_controls(True)

        def worker() -> None:
            run = self.runner.resume if self.resume_session_id else self.runner.run_selected
            if self.resume_session_id:
                run(
                    session.id,
                    self.controller.state.source,
                    environment,
                    on_started=lambda test: self.events.put(("started", test)),
                    on_result=lambda result: self.events.put(("result", result)),
                )
            else:
                run(
                    session.id,
                    self.controller.state.source,
                    tests,
                    environment,
                    on_started=lambda test: self.events.put(("started", test)),
                    on_result=lambda result: self.events.put(("result", result)),
                )
            self.events.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()
        self.resume_session_id = None

    def stop_run(self) -> None:
        self.runner.stop()
        self.status.set("⏸ Stopping after current test…")
        self.stop_button.configure(state="disabled")

    def _drain_events(self) -> None:
        if getattr(self, "_destroyed", False):
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "started":
                    self.status.set(f"⏱ Running: {value.test_id or value.display_name}")
                elif kind == "result":
                    self.result_by_name[value.function_name] = value
                    self.bar["value"] += 1
                    self.progress.set(f"Running tests… {int(self.bar['value'])} / {int(self.bar['maximum'])}")
                    self._render_tests()
                    self._show_details(value)
                elif kind == "done":
                    self.running = False
                    session = self.database.get_session(self.current_session_id)
                    self.status.set("⏸ Paused" if session.status == SessionStatus.PAUSED else "✓ Complete")
                    self.progress.set(f"{session.completed_tests} / {session.total_tests} completed")
                    self._set_running_controls(False)
        except queue.Empty:
            pass
        if not getattr(self, "_destroyed", False):
            self._drain_job = self.after(80, self._drain_events)

    def _set_running_controls(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.parse_button.configure(state=state)
        self.run_selected_button.configure(state=state)
        self.run_all_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def clear_result_details(self) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def _show_details(self, result) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")

        # Status & Timing Banner
        status_str = str(result.status)
        badge_tag = "badge_pass" if status_str == "PASS" else ("badge_fail" if status_str == "FAIL" else "badge_error")
        self.details.insert("end", "STATUS:   ", "key")
        self.details.insert("end", f"{STATUS_MARK.get(status_str, status_str)}\n", badge_tag)

        if result.duration_ms is not None:
            self.details.insert("end", "DURATION: ", "key")
            self.details.insert("end", f"{result.duration_ms} ms\n", "code")

        if getattr(result, "function_name", None):
            self.details.insert("end", "FUNCTION: ", "key")
            func_name = result.function_name
            if getattr(result, "test_id", None):
                func_name += f" [{result.test_id}]"
            self.details.insert("end", f"{func_name}\n", "code")

        # HTTP Request Section
        if getattr(result, "url", None) or getattr(result, "http_method", None):
            self.details.insert("end", "\n── REQUEST ──────────────────────────────────────────────────────────\n", "section")
            self.details.insert("end", f"Method: {result.http_method or 'GET'}\n", "code")
            self.details.insert("end", f"URL:    {result.url or ''}\n", "code")

        # HTTP Response Section
        if getattr(result, "http_status", None) is not None or getattr(result, "response_body", None):
            self.details.insert("end", "\n── RESPONSE ─────────────────────────────────────────────────────────\n", "section")
            if result.http_status is not None:
                self.details.insert("end", f"Status Code: {result.http_status}\n", "code")
            if result.response_body:
                self.details.insert("end", f"Body:\n{result.response_body}\n", "code")

        # Assertions / Error Section
        if getattr(result, "error_message", None):
            self.details.insert("end", "\n── ASSERTION / ERROR ────────────────────────────────────────────────\n", "section")
            self.details.insert("end", f"{result.error_message}\n", "error_code")

        # Output Section (Stdout / Stderr)
        if getattr(result, "stdout", None):
            self.details.insert("end", "\n── STDOUT ───────────────────────────────────────────────────────────\n", "section")
            self.details.insert("end", f"{result.stdout}\n", "code")
        if getattr(result, "stderr", None):
            self.details.insert("end", "\n── STDERR ───────────────────────────────────────────────────────────\n", "section")
            self.details.insert("end", f"{result.stderr}\n", "error_code")

        self.details.configure(state="disabled")

    def _update_summary(self) -> None:
        statuses = [str(r.status) for r in self.result_by_name.values()]
        total = len(self.controller.state.tests)
        passed = statuses.count("PASS")
        failed = statuses.count("FAIL")
        errors = statuses.count("ERROR")
        not_run = total - len(statuses)
        self.summary.set(
            f"{total} Tests  •  {passed} PASS  •  {failed} FAIL  •  {errors} ERROR  •  {max(0, not_run)} NOT RUN"
        )

    def copy_llm_message(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(LLM_MESSAGE)
        self.update()
        self.status.set("✓ Script contract copied to clipboard!")

    def export_report(self, report_type: str, session_id: int | None = None) -> None:
        session_id = session_id or self.current_session_id
        if not session_id or not self.database.session_results(session_id):
            messagebox.showinfo("No results to export", "There's no test result data to export yet.", parent=self); return
        extension = report_type.lower()
        path = filedialog.asksaveasfilename(parent=self, title=f"Export {extension.upper()} report", defaultextension=f".{extension}",
            filetypes=[(f"{extension.upper()} report", f"*.{extension}"), ("All files", "*.*")])
        if not path: return
        generator = ReportGenerator(self.database, self._environment())
        try:
            getattr(generator, f"generate_{extension}_report")(session_id, path)
        except OSError as error:
            messagebox.showerror("Export failed", f"PostBaby could not save the report.\n\n{error}", parent=self); return
        self.status.set(f"✓ Report exported: {Path(path).name}")
        messagebox.showinfo("Report exported", f"Saved report to:\n{path}", parent=self)

    def show_recovery(self, sessions) -> None:
        lines = [f"Session #{s.id}: {s.completed_tests} / {s.total_tests} completed" for s in sessions]
        if messagebox.askyesno("🍼 Welcome Back", "Looks like a test run was interrupted.\n\n" + "\n".join(lines) + "\n\nResume the most recent session?", parent=self):
            session = sessions[0]; source = self.database.latest_script_snapshot(session.id)
            self.show_runner()
            if source:
                self.editor.delete("1.0", "end"); self.editor.insert("1.0", source); self.parse_script()
            self.resume_session_id = session.id
            self.status.set(f"⏸ Ready to resume Session #{session.id}")

    def show_history(self) -> None:
        window = tk.Toplevel(self); window.title("PostBaby — Session History"); window.geometry("650x360")
        tree = ttk.Treeview(window, columns=("project", "progress", "status", "results"), show="headings")
        for key, title in (("project", "Project"), ("progress", "Progress"), ("status", "Status"), ("results", "Results")):
            tree.heading(key, text=title); tree.column(key, width=145)
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for row in self.database.session_history():
            tree.insert("", "end", iid=str(row["id"]), values=(row["project_name"], f"{row['completed_tests']} / {row['total_tests']}", row["status"], f"{row['passed']} PASS  {row['failed']} FAIL  {row['errors']} ERROR"))
        def view() -> None:
            selection = tree.selection()
            if not selection: return
            sid = int(selection[0]); source = self.database.latest_script_snapshot(sid)
            session = self.database.get_session(sid)
            if session:
                proj = self.database.connection.execute("SELECT name FROM projects WHERE id=?", (session.project_id,)).fetchone()
                if proj: self.project_name.set(proj["name"])
            self.show_runner()
            if source: self.editor.delete("1.0", "end"); self.editor.insert("1.0", source); self.parse_script()
            for row in self.database.session_results(sid): self.result_by_name[row["function_name"]] = type("Result", (), dict(row))()
            self._render_tests()
            self._mark_clean()
            window.destroy()
        def export_selected(report_type: str) -> None:
            selection = tree.selection()
            if selection: self.export_report(report_type, int(selection[0]))
        controls = ttk.Frame(window); controls.pack(pady=(0, 10))
        ttk.Button(controls, text="View Results", command=view).pack(side="left", padx=3)
        ttk.Button(controls, text="Export HTML", command=lambda: export_selected("html")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export JSON", command=lambda: export_selected("json")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export CSV", command=lambda: export_selected("csv")).pack(side="left", padx=3)

    def destroy(self) -> None:
        self._destroyed = True
        if hasattr(self, "_drain_job"):
            try: self.after_cancel(self._drain_job)
            except Exception: pass
        try:
            self.eval('foreach id [after info] {after cancel $id}')
        except Exception: pass
        super().destroy()

    def _close(self, prompt: bool = True) -> None:
        if getattr(self, "_destroyed", False):
            return
        if prompt and hasattr(self, "editor") and self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
            elif choice == "cancel":
                return
        if self.running:
            self.runner.stop()
        self.database.close()
        self.destroy()


def main() -> None:
    PostBabyApp().mainloop()


if __name__ == "__main__":
    main()
