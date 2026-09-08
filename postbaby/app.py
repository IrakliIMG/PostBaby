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
from .paths import default_database_path, resource_path

SAMPLE_PATH = resource_path("samples", "example_api_tests.py")
STATUS_MARK = {"PASS": "✓ PASS", "FAIL": "✗ FAIL", "ERROR": "⚠ ERROR", "RUNNING": "⏱ RUNNING", "NOT_RUN": "○ NOT RUN", "SKIPPED": "– SKIPPED", "INTERRUPTED": "⚠ INTERRUPTED"}


class PostBabyApp(tk.Tk):
    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("PostBaby 🍼")
        self.geometry("1120x780")
        self.minsize(850, 620)
        self.database = Database(db_path or default_database_path())
        self.controller = ApplicationController(self.database)
        self.runner = TestRunner(self.database)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.result_by_name: dict[str, Any] = {}
        self.current_session_id: int | None = None
        self.resume_session_id: int | None = None
        self.running = False
        self.env_vars = {key: tk.StringVar() for key in ("BASE_URL", "USERNAME", "PASSWORD", "TOKEN", "API_KEY", "CLIENT_ID", "CLIENT_SECRET")}
        self.project_name = tk.StringVar(value="My API Project")
        self.status = tk.StringVar(value="● Ready")
        self.progress = tk.StringVar(value="No tests parsed")
        self._menu()
        self.show_welcome()
        interrupted = self.database.recover_interrupted_sessions()
        if interrupted:
            self.after(150, lambda: self.show_recovery(interrupted))
        self.after(80, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Session", command=self.show_runner)
        file_menu.add_command(label="Session History", command=self.show_history)
        file_menu.add_separator(); file_menu.add_command(label="Exit", command=self._close)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Validate Script", command=self.parse_script)
        tools.add_command(label="Copy LLM Message", command=self.copy_llm_message)
        menu.add_cascade(label="File", menu=file_menu); menu.add_cascade(label="Tools", menu=tools)
        self.config(menu=menu)

    def _clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def show_welcome(self) -> None:
        self._clear()
        panel = ttk.Frame(self, padding=40)
        panel.place(relx=.5, rely=.46, anchor="center")
        ttk.Label(panel, text="🍼", font=("Segoe UI Emoji", 44)).pack()
        ttk.Label(panel, text="POSTBABY", font=("Segoe UI", 26, "bold")).pack(pady=(10, 4))
        ttk.Label(panel, text="Meet your new testing buddy.\n\nPostBaby runs your API tests.\nYour LLM writes them.", justify="center").pack(pady=8)
        ttk.Button(panel, text="📋  COPY MESSAGE", command=self.copy_llm_message).pack(fill="x", pady=(18, 7))
        ttk.Button(panel, text="🧪  OPEN TEST RUNNER", command=self.show_runner).pack(fill="x")

    def show_runner(self) -> None:
        self._clear()
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True)
        header = ttk.Frame(root); header.pack(fill="x")
        ttk.Label(header, text="🍼  POSTBABY", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.status).pack(side="right")
        env = ttk.LabelFrame(root, text=" Environment ", padding=8); env.pack(fill="x", pady=(10, 7))
        ttk.Label(env, text="Project name").grid(row=0, column=0, sticky="w"); ttk.Entry(env, textvariable=self.project_name, width=32).grid(row=0, column=1, sticky="ew", padx=(6, 16))
        names = [("Base URL", "BASE_URL", False), ("Username", "USERNAME", False), ("Password", "PASSWORD", True), ("Token", "TOKEN", True), ("API Key", "API_KEY", True), ("Client ID", "CLIENT_ID", False), ("Client Secret", "CLIENT_SECRET", True)]
        for i, (label, key, secret) in enumerate(names, start=1):
            col, row = (0, i) if i <= 4 else (2, i - 4)
            ttk.Label(env, text=label).grid(row=row, column=col, sticky="w", pady=2)
            ttk.Entry(env, textvariable=self.env_vars[key], show="•" if secret else "", width=32).grid(row=row, column=col + 1, sticky="ew", padx=(6, 16), pady=2)
        env.columnconfigure(1, weight=1); env.columnconfigure(3, weight=1)
        script_box = ttk.LabelFrame(root, text=" Python Test Script ", padding=6); script_box.pack(fill="both", expand=True, pady=5)
        self.editor = tk.Text(script_box, height=13, wrap="none", font=("Consolas", 10), undo=True)
        yscroll = ttk.Scrollbar(script_box, orient="vertical", command=self.editor.yview); xscroll = ttk.Scrollbar(script_box, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.editor.grid(row=0, column=0, sticky="nsew"); yscroll.grid(row=0, column=1, sticky="ns"); xscroll.grid(row=1, column=0, sticky="ew")
        script_box.columnconfigure(0, weight=1); script_box.rowconfigure(0, weight=1)
        try: self.editor.insert("1.0", SAMPLE_PATH.read_text())
        except OSError: pass
        actions = ttk.Frame(root); actions.pack(fill="x", pady=5)
        self.parse_button = ttk.Button(actions, text="Parse Tests", command=self.parse_script); self.parse_button.pack(side="left")
        ttk.Button(actions, text="Clear", command=lambda: self.editor.delete("1.0", "end")).pack(side="left", padx=5)
        self.run_selected_button = ttk.Button(actions, text="▶ Run Selected", command=lambda: self.start_run(True)); self.run_selected_button.pack(side="right", padx=4)
        self.run_all_button = ttk.Button(actions, text="▶ Run All", command=lambda: self.start_run(False)); self.run_all_button.pack(side="right", padx=4)
        self.stop_button = ttk.Button(actions, text="■ Stop", command=self.stop_run, state="disabled"); self.stop_button.pack(side="right", padx=4)
        self.bar = ttk.Progressbar(root, mode="determinate"); self.bar.pack(fill="x")
        ttk.Label(root, textvariable=self.progress).pack(anchor="w")
        panes = ttk.PanedWindow(root, orient="horizontal"); panes.pack(fill="both", expand=True, pady=6)
        left = ttk.LabelFrame(panes, text=" Test Cases ", padding=5); right = ttk.LabelFrame(panes, text=" Result Details ", padding=5); panes.add(left, weight=1); panes.add(right, weight=1)
        controls = ttk.Frame(left); controls.pack(fill="x")
        ttk.Button(controls, text="Select All", command=lambda: self._select_all(True)).pack(side="left")
        ttk.Button(controls, text="Clear Selection", command=lambda: self._select_all(False)).pack(side="left", padx=4)
        self.tree = ttk.Treeview(left, columns=("test", "status", "duration"), show="headings", selectmode="browse")
        for col, title, width in (("test", "Test", 290), ("status", "Status", 120), ("duration", "Duration", 75)):
            self.tree.heading(col, text=title); self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=5); self.tree.bind("<ButtonRelease-1>", self._toggle_or_details)
        self.details = tk.Text(right, wrap="word", font=("Consolas", 10), state="disabled"); detail_scroll = ttk.Scrollbar(right, command=self.details.yview); self.details.configure(yscrollcommand=detail_scroll.set)
        self.details.pack(side="left", fill="both", expand=True); detail_scroll.pack(side="right", fill="y")
        footer = ttk.Frame(root); footer.pack(fill="x")
        self.summary = tk.StringVar(value="0 Tests  •  0 PASS  •  0 FAIL  •  0 ERROR")
        ttk.Label(footer, textvariable=self.summary).pack(side="left")
        ttk.Button(footer, text="📋 Copy LLM Message", command=self.copy_llm_message).pack(side="right")
        ttk.Button(footer, text="Session History", command=self.show_history).pack(side="right", padx=5)
        ttk.Button(footer, text="Export CSV", command=lambda: self.export_report("csv")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export JSON", command=lambda: self.export_report("json")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export HTML", command=lambda: self.export_report("html")).pack(side="right", padx=3)
        self.parse_script()

    def parse_script(self) -> None:
        result = self.controller.state.parse(self.editor.get("1.0", "end-1c"))
        self.result_by_name.clear(); self._render_tests()
        if result.valid:
            self.status.set(f"✓ Script valid — {len(result.parse_result.tests)} test cases")
            if result.warnings: messagebox.showwarning("Script warnings", "\n".join(result.warnings), parent=self)
        else:
            self.status.set("✗ Script validation failed")
            messagebox.showerror("PostBaby could not validate this script.", "\n".join(result.errors), parent=self)

    def _render_tests(self) -> None:
        for item in self.tree.get_children(): self.tree.delete(item)
        for test in self.controller.state.tests:
            result = self.result_by_name.get(test.function_name)
            selected = "☑" if test.function_name in self.controller.state.selected else "☐"
            title = f"{selected} {test.test_id or ''} {test.display_name}".strip()
            status = STATUS_MARK.get(str(result.status), str(result.status)) if result else STATUS_MARK["NOT_RUN"]
            duration = f"{result.duration_ms} ms" if result and result.duration_ms is not None else ""
            self.tree.insert("", "end", iid=test.function_name, values=(title, status, duration))
        self._update_summary()

    def _toggle_or_details(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if not item: return
        if self.tree.identify_column(event.x) == "#1":
            self.controller.state.set_selected(item, item not in self.controller.state.selected)
            self._render_tests()
        result = self.result_by_name.get(item)
        if result: self._show_details(result)

    def _select_all(self, selected: bool) -> None:
        self.controller.state.selected = {t.function_name for t in self.controller.state.tests} if selected else set(); self._render_tests()

    def _environment(self) -> dict[str, str]:
        return {name: value.get() for name, value in self.env_vars.items()}

    def start_run(self, selected_only: bool) -> None:
        if not self.controller.state.tests: self.parse_script()
        if not self.controller.state.tests: return
        environment = self._environment()
        if not environment["BASE_URL"] and "{{BASE_URL}}" in self.controller.state.source:
            messagebox.showerror("Missing Base URL", "Base URL is required before running these tests.", parent=self); return
        try:
            if self.resume_session_id:
                session = self.database.get_session(self.resume_session_id)
                tests = self.database.unfinished_tests(session.id)
            else:
                session, tests = self.controller.start_session(self.project_name.get(), environment, selected_only)
        except ValueError as error: messagebox.showerror("Cannot start run", str(error), parent=self); return
        self.current_session_id, self.running = session.id, True
        self.bar.configure(maximum=len(tests), value=0); self.progress.set(f"Running tests… 0 / {len(tests)}")
        self.status.set("⏱ Running"); self._set_running_controls(True)
        def worker() -> None:
            run = self.runner.resume if self.resume_session_id else self.runner.run_selected
            run(session.id, self.controller.state.source, environment, on_started=lambda test: self.events.put(("started", test)), on_result=lambda result: self.events.put(("result", result))) if self.resume_session_id else run(session.id, self.controller.state.source, tests, environment,
                on_started=lambda test: self.events.put(("started", test)), on_result=lambda result: self.events.put(("result", result)))
            self.events.put(("done", None))
        threading.Thread(target=worker, daemon=True).start()
        self.resume_session_id = None

    def stop_run(self) -> None:
        self.runner.stop(); self.status.set("⏸ Stopping after current test…"); self.stop_button.configure(state="disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "started": self.status.set(f"⏱ Running: {value.test_id or value.display_name}")
                elif kind == "result":
                    self.result_by_name[value.function_name] = value; self.bar["value"] += 1
                    self.progress.set(f"Running tests… {int(self.bar['value'])} / {int(self.bar['maximum'])}"); self._render_tests(); self._show_details(value)
                elif kind == "done":
                    self.running = False; session = self.database.get_session(self.current_session_id)
                    self.status.set("⏸ Paused" if session.status == SessionStatus.PAUSED else "✓ Complete")
                    self.progress.set(f"{session.completed_tests} / {session.total_tests} completed"); self._set_running_controls(False)
        except queue.Empty: pass
        self.after(80, self._drain_events)

    def _set_running_controls(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.parse_button.configure(state=state); self.run_selected_button.configure(state=state); self.run_all_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _show_details(self, result) -> None:
        rows = [("Status", result.status), ("Duration", f"{result.duration_ms} ms" if result.duration_ms is not None else None),
                ("HTTP", f"{result.http_method or ''} {result.url or ''} {result.http_status or ''}".strip()),
                ("Message", result.error_message), ("Stdout", result.stdout), ("Stderr", result.stderr), ("Response", result.response_body)]
        text = "\n\n".join(f"{key}\n{value}" for key, value in rows if value)
        self.details.configure(state="normal"); self.details.delete("1.0", "end"); self.details.insert("1.0", text); self.details.configure(state="disabled")

    def _update_summary(self) -> None:
        statuses = [str(r.status) for r in self.result_by_name.values()]
        self.summary.set(f"{len(self.controller.state.tests)} Tests  •  {statuses.count('PASS')} PASS  •  {statuses.count('FAIL')} FAIL  •  {statuses.count('ERROR')} ERROR  •  {len(self.controller.state.tests)-len(statuses)} NOT RUN")

    def copy_llm_message(self) -> None:
        self.clipboard_clear(); self.clipboard_append(LLM_MESSAGE); self.update()
        self.status.set("✓ LLM message copied!")

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
            self.show_runner(); sid = int(selection[0]); source = self.database.latest_script_snapshot(sid)
            if source: self.editor.delete("1.0", "end"); self.editor.insert("1.0", source); self.parse_script()
            for row in self.database.session_results(sid): self.result_by_name[row["function_name"]] = type("Result", (), dict(row))()
            self._render_tests(); window.destroy()
        def export_selected(report_type: str) -> None:
            selection = tree.selection()
            if selection: self.export_report(report_type, int(selection[0]))
        controls = ttk.Frame(window); controls.pack(pady=(0, 10))
        ttk.Button(controls, text="View Results", command=view).pack(side="left", padx=3)
        ttk.Button(controls, text="Export HTML", command=lambda: export_selected("html")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export JSON", command=lambda: export_selected("json")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export CSV", command=lambda: export_selected("csv")).pack(side="left", padx=3)

    def _close(self) -> None:
        if self.running: self.runner.stop()
        self.database.close(); self.destroy()


def main() -> None:
    PostBabyApp().mainloop()


if __name__ == "__main__":
    main()
