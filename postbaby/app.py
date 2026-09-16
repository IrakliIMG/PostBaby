"""Tkinter desktop application for the PostBaby execution core."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from .assets import ensure_icon_assets
from .controller import ApplicationController
from .database import Database
from .llm_message import LLM_MESSAGE
from .models import SessionStatus, TestStatus
from .paths import default_database_path
from .report import ReportGenerator
from .runner import TestRunner

STATUS_MARK = {
    "PASS": "✓ PASS",
    "FAIL": "✗ FAIL",
    "ERROR": "⚠ ERROR",
    "RUNNING": "⏱ RUNNING",
    "NOT_RUN": "○ NOT RUN",
    "SKIPPED": "– SKIPPED",
    "INTERRUPTED": "⚠ INTERRUPTED",
}

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0F141C",
        "header_bg": "#161D27",
        "sidebar_bg": "#131822",
        "card_bg": "#1A2230",
        "card_border": "#283446",
        "card_hover": "#222D3E",
        "active_bg": "#253347",
        "text_primary": "#E2E8F0",
        "text_secondary": "#94A3B8",
        "text_muted": "#64748B",
        "accent": "#38BDF8",
        "accent_hover": "#0EA5E9",
        "btn_primary_bg": "#0284C7",
        "btn_primary_fg": "#FFFFFF",
        "btn_danger_bg": "#EF4444",
        "btn_danger_fg": "#FFFFFF",
        "btn_secondary_bg": "#263346",
        "btn_secondary_fg": "#CBD5E1",
        "entry_bg": "#0F141C",
        "entry_fg": "#F1F5F9",
        "entry_border": "#334155",
        "editor_bg": "#0B0F17",
        "editor_fg": "#E2E8F0",
        "editor_insert": "#38BDF8",
        "gutter_bg": "#0B0F17",
        "gutter_fg": "#475569",
        "highlight_focus": "#1E3A5F",
        "highlight_selected": "#16273C",
        "status_pass": "#22C55E",
        "status_fail": "#EF4444",
        "status_error": "#F59E0B",
        "status_running": "#38BDF8",
        "status_not_run": "#64748B",
    },
    "light": {
        "bg": "#F1F5F9",
        "header_bg": "#FFFFFF",
        "sidebar_bg": "#F8FAFC",
        "card_bg": "#FFFFFF",
        "card_border": "#E2E8F0",
        "card_hover": "#F1F5F9",
        "active_bg": "#E0F2FE",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#94A3B8",
        "accent": "#0284C7",
        "accent_hover": "#0369A1",
        "btn_primary_bg": "#0284C7",
        "btn_primary_fg": "#FFFFFF",
        "btn_danger_bg": "#DC2626",
        "btn_danger_fg": "#FFFFFF",
        "btn_secondary_bg": "#E2E8F0",
        "btn_secondary_fg": "#1E293B",
        "entry_bg": "#FFFFFF",
        "entry_fg": "#0F172A",
        "entry_border": "#CBD5E1",
        "editor_bg": "#FFFFFF",
        "editor_fg": "#0F172A",
        "editor_insert": "#0284C7",
        "gutter_bg": "#F8FAFC",
        "gutter_fg": "#94A3B8",
        "highlight_focus": "#DDF4FF",
        "highlight_selected": "#F0F9FF",
        "status_pass": "#16A34A",
        "status_fail": "#DC2626",
        "status_error": "#D97706",
        "status_running": "#0284C7",
        "status_not_run": "#64748B",
    },
}


class LineNumbers(tk.Canvas):
    """Clean, high-performance line number gutter for the Python script editor."""

    def __init__(self, parent: tk.Widget, text_widget: tk.Text, **kwargs: Any) -> None:
        super().__init__(parent, width=38, highlightthickness=0, bd=0, **kwargs)
        self.text_widget = text_widget
        self.fg_color = "#64748B"

    def set_colors(self, bg: str, fg: str) -> None:
        self.configure(bg=bg)
        self.fg_color = fg
        self.redraw()

    def redraw(self, *args: Any) -> None:
        self.delete("all")
        i = self.text_widget.index("@0,0")
        while True:
            dline = self.text_widget.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            linenum = str(i).split(".")[0]
            self.create_text(
                34,
                y + 2,
                anchor="ne",
                text=linenum,
                fill=self.fg_color,
                font=self.text_widget.cget("font"),
            )
            i = self.text_widget.index(f"{i}+1line")


class PostBabyApp(tk.Tk):
    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("PostBaby 🍼")
        self.geometry("1180x820")
        self.minsize(920, 660)

        # Assets & Window Icon
        self.ico_path, self.png_path = ensure_icon_assets()
        try:
            self.pacifier_photo = tk.PhotoImage(file=str(self.png_path))
            self.iconphoto(True, self.pacifier_photo)
        except Exception:
            self.pacifier_photo = None

        self.database = Database(db_path or default_database_path())
        self.controller = ApplicationController(self.database)
        self.runner = TestRunner(self.database)

        self.theme_mode = self.database.get_setting("theme", "dark") or "dark"
        if self.theme_mode not in THEMES:
            self.theme_mode = "dark"

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.result_by_name: dict[str, Any] = {}
        self.current_session_id: int | None = None
        self.resume_session_id: int | None = None
        self.running = False
        self.focused_function: str | None = None

        self.env_vars = {
            key: tk.StringVar()
            for key in ("BASE_URL", "USERNAME", "PASSWORD", "TOKEN", "API_KEY", "CLIENT_ID", "CLIENT_SECRET")
        }
        self.project_name = tk.StringVar(value="My API Project")
        self.save_status = tk.StringVar(value="✓ Saved")
        self.status = tk.StringVar(value="● Ready")
        self.progress = tk.StringVar(value="No tests parsed")
        self.summary = tk.StringVar(value="0 Tests  •  0 PASS  •  0 FAIL  •  0 ERROR")

        self._saved_project_name = "My API Project"
        self._saved_source = ""
        self._saved_env = {k: "" for k in self.env_vars}

        self._setup_styles()
        self._bind_shortcuts()
        self._menu()

        self.show_welcome()

        interrupted = self.database.recover_interrupted_sessions()
        if interrupted:
            self.after(150, lambda: self.show_recovery(interrupted))

        self._drain_job = self.after(80, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-s>", lambda e: (self.save_project(), "break")[1])
        self.bind_all("<Control-S>", lambda e: (self.save_project(), "break")[1])
        self.bind_all("<Control-Return>", lambda e: (self.start_run(True), "break")[1])

    def _theme(self) -> dict[str, str]:
        return THEMES[self.theme_mode]

    def _setup_styles(self) -> None:
        t = self._theme()
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.configure(bg=t["bg"])

        # Base font and colors
        style.configure(".", font=("Segoe UI", 9), background=t["bg"], foreground=t["text_primary"])
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabel", background=t["bg"], foreground=t["text_primary"], font=("Segoe UI", 9))

        # Typography
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"), foreground=t["text_primary"])
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground=t["text_primary"])
        style.configure("Brand.TLabel", font=("Segoe UI", 22, "bold"), foreground=t["text_primary"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground=t["text_secondary"])
        style.configure("Required.TLabel", font=("Segoe UI", 9, "bold"), foreground=t["text_primary"])
        style.configure("Saved.TLabel", font=("Segoe UI", 9, "bold"), foreground=t["status_pass"])
        style.configure("Unsaved.TLabel", font=("Segoe UI", 9, "bold"), foreground=t["status_error"])

        # Sidebar styles
        style.configure("Sidebar.TFrame", background=t["sidebar_bg"])
        style.configure("Sidebar.TLabel", background=t["sidebar_bg"], foreground=t["text_secondary"])
        style.configure("SidebarHeader.TLabel", background=t["sidebar_bg"], foreground=t["text_primary"], font=("Segoe UI", 10, "bold"))

        # Card frames
        style.configure("Card.TFrame", background=t["card_bg"], relief="flat")
        style.configure("TLabelframe", background=t["card_bg"], bordercolor=t["card_border"], relief="solid", borderwidth=1, padding=8)
        style.configure("TLabelframe.Label", background=t["card_bg"], font=("Segoe UI", 9, "bold"), foreground=t["accent"])

        # Buttons
        style.configure("TButton", font=("Segoe UI", 9), padding=(8, 4), background=t["card_bg"], foreground=t["text_primary"], bordercolor=t["card_border"])
        style.map("TButton",
                  background=[("active", t["card_hover"]), ("disabled", t["bg"])],
                  foreground=[("disabled", t["text_muted"])])

        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), padding=(10, 5), background=t["btn_primary_bg"], foreground=t["btn_primary_fg"])
        style.map("Primary.TButton", background=[("active", t["accent_hover"])])

        style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"), padding=(8, 4), background=t["btn_danger_bg"], foreground=t["btn_danger_fg"])
        style.map("Danger.TButton", background=[("active", "#DC2626")])

        style.configure("Icon.TButton", font=("Segoe UI", 10), padding=(4, 2), relief="flat")

        # Treeview
        style.configure("Treeview", background=t["card_bg"], foreground=t["text_primary"], fieldbackground=t["card_bg"], font=("Segoe UI", 9), rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=t["header_bg"], foreground=t["text_secondary"], font=("Segoe UI", 9, "bold"), padding=(6, 4), borderwidth=0)
        style.map("Treeview", background=[("selected", t["active_bg"])], foreground=[("selected", t["text_primary"])])

        # Progress bar
        style.configure("TProgressbar", thickness=6, background=t["accent"], troughcolor=t["card_bg"], borderwidth=0)

    def toggle_theme(self) -> None:
        new_mode = "light" if self.theme_mode == "dark" else "dark"
        self.set_theme(new_mode)

    def set_theme(self, mode: str) -> None:
        if mode not in THEMES:
            return
        self.theme_mode = mode
        self.database.set_setting("theme", mode)
        self._setup_styles()
        # Refresh active screen
        if hasattr(self, "editor") and self.editor.winfo_exists():
            self._apply_editor_theme()
            self._render_tests()
            self._update_code_highlighting(self.focused_function, scroll_to_focus=False)
            if hasattr(self, "details") and self.details.winfo_exists():
                self._apply_details_theme()
        elif hasattr(self, "_welcome_root") and self._welcome_root.winfo_exists():
            self.show_welcome()
        elif hasattr(self, "_projects_root") and self._projects_root.winfo_exists():
            self.show_projects()

    def _apply_editor_theme(self) -> None:
        t = self._theme()
        if hasattr(self, "editor"):
            self.editor.configure(
                bg=t["editor_bg"],
                fg=t["editor_fg"],
                insertbackground=t["editor_insert"],
                selectbackground=t["highlight_focus"],
                selectforeground=t["text_primary"],
            )
            self.editor.tag_configure("focused_test", background=t["highlight_focus"])
            self.editor.tag_configure("selected_test", background=t["highlight_selected"])
            self.editor.tag_raise("focused_test", "selected_test")

        if hasattr(self, "line_numbers"):
            self.line_numbers.set_colors(t["gutter_bg"], t["gutter_fg"])

    def _apply_details_theme(self) -> None:
        t = self._theme()
        if hasattr(self, "details"):
            self.details.configure(
                bg=t["editor_bg"],
                fg=t["editor_fg"],
                insertbackground=t["editor_insert"],
            )
            self.details.tag_configure("badge_pass", font=("Segoe UI", 9, "bold"), foreground=t["status_pass"])
            self.details.tag_configure("badge_fail", font=("Segoe UI", 9, "bold"), foreground=t["status_fail"])
            self.details.tag_configure("badge_error", font=("Segoe UI", 9, "bold"), foreground=t["status_error"])
            self.details.tag_configure("section", font=("Segoe UI", 9, "bold"), foreground=t["accent"])
            self.details.tag_configure("key", font=("Segoe UI", 9, "bold"), foreground=t["text_secondary"])
            self.details.tag_configure("code", font=("Consolas", 10), foreground=t["text_primary"])
            self.details.tag_configure("error_code", font=("Consolas", 10), foreground=t["status_fail"])

    def _menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Project... (Ctrl+N)", command=self.prompt_new_project)
        file_menu.add_command(label="Open Project...", command=self.show_projects)
        file_menu.add_command(label="Save Project (Ctrl+S)", command=self.save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Session History", command=self.show_history)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Toggle Dark / Light Theme", command=self.toggle_theme)

        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Validate Script", command=self.parse_script)
        tools.add_command(label="Copy Script Contract", command=self.copy_llm_message)

        menu.add_cascade(label="File", menu=file_menu)
        menu.add_cascade(label="View", menu=view_menu)
        menu.add_cascade(label="Tools", menu=tools)
        self.configure(menu=menu)

    def _clear(self) -> None:
        for child in list(self.children.values()):
            if isinstance(child, tk.Menu):
                continue
            child.destroy()
        if hasattr(self, "editor"):
            del self.editor
        if hasattr(self, "line_numbers"):
            del self.line_numbers
        if hasattr(self, "details"):
            del self.details
        if hasattr(self, "tree"):
            del self.tree

    def is_dirty(self) -> bool:
        if self.project_name.get() != self._saved_project_name:
            return True
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists():
            try:
                if self.editor.get("1.0", "end-1c") != self._saved_source:
                    return True
            except Exception:
                pass
        for k, v in self.env_vars.items():
            if v.get() != self._saved_env.get(k, ""):
                return True
        return False

    def _mark_clean(self) -> None:
        self._saved_project_name = self.project_name.get()
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists():
            try:
                self._saved_source = self.editor.get("1.0", "end-1c")
            except Exception:
                pass
        self._saved_env = {k: v.get() for k, v in self.env_vars.items()}
        self.save_status.set("✓ Saved")

    def _on_modified(self) -> None:
        if self.is_dirty():
            self.save_status.set("● Unsaved changes")
        else:
            self.save_status.set("✓ Saved")

    def _on_text_modified(self, event=None) -> None:
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists() and self.editor.edit_modified():
            self._on_modified()
            if hasattr(self, "line_numbers"):
                self.line_numbers.redraw()
            self._update_code_highlighting(self.focused_function, scroll_to_focus=False)
            self.editor.edit_modified(False)

    def save_project(self) -> bool:
        name = self.project_name.get().strip()
        if not name:
            messagebox.showerror("Save Project", "Project name cannot be empty.", parent=self)
            return False

        source = self.editor.get("1.0", "end-1c") if hasattr(self, "editor") else self.controller.state.source
        meta = {k: v.get() for k, v in self.env_vars.items() if v.get()}
        meta_json = json.dumps(meta)

        project = self.database.get_or_create_project(name)

        if self.current_session_id is not None:
            existing = self.database.get_session(self.current_session_id)
            if existing and existing.project_id == project.id:
                self.database.connection.execute(
                    "UPDATE sessions SET total_tests=?, environment_metadata=?, updated_at=? WHERE id=?",
                    (len(self.controller.state.tests), meta_json, self.database.connection.execute("SELECT datetime('now')").fetchone()[0], self.current_session_id),
                )
                self.database.save_script_snapshot(self.current_session_id, source)
                self.database.connection.commit()
                self._mark_clean()
                self.status.set(f"✓ Saved project: {name}")
                return True

        latest_session = self.database.latest_project_session(project.id)
        if latest_session is not None:
            self.current_session_id = latest_session.id
            self.database.connection.execute(
                "UPDATE sessions SET total_tests=?, environment_metadata=?, updated_at=? WHERE id=?",
                (len(self.controller.state.tests), meta_json, self.database.connection.execute("SELECT datetime('now')").fetchone()[0], self.current_session_id),
            )
            self.database.save_script_snapshot(self.current_session_id, source)
            self.database.connection.commit()
        else:
            session = self.database.create_session(project.id, len(self.controller.state.tests), meta_json)
            self.current_session_id = session.id
            self.database.save_script_snapshot(session.id, source)

        self._mark_clean()
        self.status.set(f"✓ Saved project: {name}")
        return True

    def go_back(self) -> None:
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists():
            if self.is_dirty():
                choice = self._prompt_unsaved_changes()
                if choice == "save":
                    if not self.save_project():
                        return
                elif choice == "cancel":
                    return
            try:
                self.controller.state.source = self.editor.get("1.0", "end-1c")
            except Exception:
                pass
        self.show_welcome()

    def _prompt_unsaved_changes(self) -> str:
        dlg = tk.Toplevel(self)
        dlg.title("Unsaved Changes")
        dlg.geometry("420x150")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        choice = ["cancel"]

        def on_action(action: str) -> None:
            choice[0] = action
            dlg.destroy()

        t = self._theme()
        dlg.configure(bg=t["bg"])

        content = ttk.Frame(dlg, padding=(24, 20, 24, 20))
        content.pack(fill="both", expand=True)

        ttk.Label(content, text="You have unsaved changes.", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(content, text="Save before leaving this screen?", font=("Segoe UI", 9), foreground=t["text_secondary"]).pack(anchor="w", pady=(0, 16))

        btn_box = ttk.Frame(content)
        btn_box.pack(fill="x")

        ttk.Button(btn_box, text="Save & Proceed", style="Primary.TButton", command=lambda: on_action("save")).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Cancel", command=lambda: on_action("cancel")).pack(side="right", padx=6)
        ttk.Button(btn_box, text="Discard", command=lambda: on_action("discard")).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", lambda: on_action("cancel"))
        self.wait_window(dlg)
        return choice[0]

    def prompt_new_project(self) -> None:
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists() and self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
            elif choice == "cancel":
                return

        dlg = tk.Toplevel(self)
        dlg.title("New Project")
        dlg.geometry("420x165")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        t = self._theme()
        dlg.configure(bg=t["bg"])

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
        ttk.Button(btn_box, text="Create Project", style="Primary.TButton", command=create).pack(side="right", padx=(6, 0))
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
        self.focused_function = None

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

    def confirm_delete_project(self, project_id: int, project_name: str) -> bool:
        """Show a styled confirmation dialog and delete project if confirmed."""
        dlg = tk.Toplevel(self)
        dlg.title("Delete Project?")
        dlg.geometry("440x170")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        t = self._theme()
        dlg.configure(bg=t["bg"])

        confirmed = [False]

        def on_delete() -> None:
            confirmed[0] = True
            dlg.destroy()

        content = ttk.Frame(dlg, padding=(24, 20, 24, 20))
        content.pack(fill="both", expand=True)

        ttk.Label(content, text=f"Delete '{project_name}'?", font=("Segoe UI", 11, "bold"), foreground=t["status_fail"]).pack(anchor="w", pady=(0, 6))
        msg = f"Are you sure you want to delete '{project_name}'?\n\nThis permanently removes the project and all associated test runs and results."
        ttk.Label(content, text=msg, font=("Segoe UI", 9), foreground=t["text_secondary"], wraplength=380).pack(anchor="w", pady=(0, 16))

        btn_box = ttk.Frame(content)
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="Delete", style="Danger.TButton", command=on_delete).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Cancel", command=dlg.destroy).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        self.wait_window(dlg)

        if confirmed[0]:
            self.database.delete_project(project_id)
            if self.project_name.get() == project_name:
                self.project_name.set("My API Project")
                self.current_session_id = None
                self.resume_session_id = None
                self.result_by_name.clear()
                self.focused_function = None
                self.controller.state.source = ""
                self.controller.state.tests = []
                self.controller.state.selected = set()
                # Return to projects list or welcome
                projects = self.database.list_projects()
                if projects:
                    self.show_projects()
                else:
                    self.show_welcome()
            else:
                self.show_projects()
            return True
        return False

    def show_projects(self) -> None:
        if hasattr(self, "editor") and self.editor is not None and self.editor.winfo_exists() and self.is_dirty():
            choice = self._prompt_unsaved_changes()
            if choice == "save":
                if not self.save_project():
                    return
            elif choice == "cancel":
                return
        self._clear()

        t = self._theme()
        self._projects_root = ttk.Frame(self, padding=24)
        self._projects_root.pack(fill="both", expand=True)

        top_bar = ttk.Frame(self._projects_root)
        top_bar.pack(fill="x", pady=(0, 16))

        ttk.Button(top_bar, text="← Back to Welcome", command=self.show_welcome).pack(side="left")
        ttk.Label(top_bar, text="📁 Projects", font=("Segoe UI", 15, "bold")).pack(side="left", padx=(14, 0))

        # Theme toggle on right
        theme_icon = "☀ Light" if self.theme_mode == "dark" else "☾ Dark"
        ttk.Button(top_bar, text=theme_icon, command=self.toggle_theme).pack(side="right", padx=(6, 0))
        ttk.Button(top_bar, text="✨ New Project", style="Primary.TButton", command=self.prompt_new_project).pack(side="right")

        projects = self.database.list_projects()

        if not projects:
            empty_box = ttk.Frame(self._projects_root, padding=40)
            empty_box.pack(expand=True)
            ttk.Label(empty_box, text="No projects found.", font=("Segoe UI", 12, "italic"), foreground=t["text_muted"]).pack(pady=(0, 12))
            ttk.Button(empty_box, text="✨ Create First Project", style="Primary.TButton", command=self.prompt_new_project).pack()
            return

        canvas = tk.Canvas(self._projects_root, borderwidth=0, highlightthickness=0, bg=t["bg"])
        scrollbar = ttk.Scrollbar(self._projects_root, orient="vertical", command=canvas.yview)
        list_frame = ttk.Frame(canvas)

        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for p in projects:
            pid = p["id"]
            name = p["name"]
            raw_time = p["last_modified"] or ""
            fmt_time = raw_time[:19].replace("T", " ") if raw_time else "Never"
            session_count = p["session_count"]

            card = ttk.Frame(list_frame, style="TLabelframe", padding=(16, 12))
            card.pack(fill="x", expand=True, pady=4, padx=4)

            left_card = ttk.Frame(card)
            left_card.pack(side="left", fill="both", expand=True)

            ttk.Label(left_card, text=name, font=("Segoe UI", 12, "bold"), foreground=t["text_primary"]).pack(anchor="w")
            info_text = f"Last modified: {fmt_time}"
            if session_count:
                info_text += f"   •   {session_count} session{'s' if session_count != 1 else ''}"
            ttk.Label(left_card, text=info_text, font=("Segoe UI", 9), foreground=t["text_secondary"]).pack(anchor="w", pady=(3, 0))

            right_card = ttk.Frame(card)
            right_card.pack(side="right", padx=(12, 0))

            ttk.Button(
                right_card,
                text="🗑",
                style="Danger.TButton",
                width=3,
                command=lambda p_id=pid, p_name=name: self.confirm_delete_project(p_id, p_name),
            ).pack(side="right", padx=(6, 0))

            ttk.Button(
                right_card,
                text="Open",
                style="Primary.TButton",
                command=lambda p_id=pid: self.open_project(p_id),
            ).pack(side="right")

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
                meta = json.loads(raw_meta)
                for k in ("BASE_URL", "USERNAME", "CLIENT_ID"):
                    if k in meta:
                        self.env_vars[k].set(meta[k])
            except Exception:
                pass

        session = self.database.latest_project_session(project_id)
        self.current_session_id = session.id if session else None
        self.resume_session_id = None
        self.result_by_name.clear()
        self.focused_function = None

        script = self.database.latest_project_script(project_id) or ""
        self.controller.state.source = script

        self.show_runner()

        if self.current_session_id:
            for r_row in self.database.session_results(self.current_session_id):
                self.result_by_name[r_row["function_name"]] = type("Result", (), dict(r_row))()

        self.parse_script(clear_results=False)
        self._render_tests()
        self._mark_clean()
        self.save_status.set("✓ Saved")
        self.status.set(f"● Opened: {p_row['name']}")

    def show_welcome(self) -> None:
        self._clear()
        t = self._theme()

        self._welcome_root = ttk.Frame(self, padding=40)
        self._welcome_root.pack(fill="both", expand=True)

        # Top corner theme toggle
        top_bar = ttk.Frame(self._welcome_root)
        top_bar.pack(fill="x")
        theme_label = "☀ Light" if self.theme_mode == "dark" else "☾ Dark"
        ttk.Button(top_bar, text=theme_label, command=self.toggle_theme).pack(side="right")

        panel = ttk.Frame(self._welcome_root)
        panel.pack(expand=True)

        if self.pacifier_photo:
            logo_lbl = ttk.Label(panel, image=self.pacifier_photo)
            logo_lbl.pack(pady=(0, 10))
        else:
            ttk.Label(panel, text="🍼", font=("Segoe UI Emoji", 36)).pack(pady=(0, 6))

        ttk.Label(panel, text="POSTBABY", font=("Segoe UI", 24, "bold"), foreground=t["text_primary"]).pack(pady=(2, 2))
        ttk.Label(panel, text="Modern Lightweight API Test Runner", font=("Segoe UI", 11), foreground=t["text_secondary"]).pack(pady=(0, 28))

        has_projects = bool(self.database.list_projects())
        btn_box = ttk.Frame(panel)
        btn_box.pack(fill="x")

        ttk.Button(btn_box, text="✨  New Project", style="Primary.TButton", command=self.prompt_new_project, width=28).pack(pady=5)
        if has_projects:
            ttk.Button(btn_box, text="📁  Open Existing Project", command=self.show_projects, width=28).pack(pady=5)
        ttk.Button(btn_box, text="📋  Copy Script Contract", command=self.copy_llm_message, width=28).pack(pady=5)

    def show_runner(self) -> None:
        self._clear()
        t = self._theme()

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # ── Header Chrome ───────────────────────────────────────────────────
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 8))

        left_header = ttk.Frame(header)
        left_header.pack(side="left")

        if self.pacifier_photo:
            icon_lbl = ttk.Label(left_header, image=self.pacifier_photo)
            icon_lbl.pack(side="left", padx=(0, 6))

        ttk.Button(left_header, text="← Welcome", command=self.go_back).pack(side="left", padx=(0, 10))
        ttk.Button(left_header, text="📁 Projects", command=self.show_projects).pack(side="left", padx=(0, 10))
        ttk.Label(left_header, text="Project:", font=("Segoe UI", 10, "bold"), foreground=t["text_secondary"]).pack(side="left", padx=(0, 6))
        ttk.Label(left_header, textvariable=self.project_name, font=("Segoe UI", 12, "bold"), foreground=t["accent"]).pack(side="left")

        right_header = ttk.Frame(header)
        right_header.pack(side="right")

        theme_text = "☀ Light" if self.theme_mode == "dark" else "☾ Dark"
        ttk.Button(right_header, text=theme_text, command=self.toggle_theme).pack(side="right", padx=(6, 0))
        ttk.Button(right_header, text="📋 Contract", command=self.copy_llm_message).pack(side="right", padx=(6, 0))
        ttk.Button(right_header, text="💾 Save (Ctrl+S)", style="Primary.TButton", command=self.save_project).pack(side="right", padx=(6, 0))
        ttk.Label(right_header, textvariable=self.save_status, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(0, 10))
        ttk.Label(right_header, textvariable=self.status, font=("Segoe UI", 9), foreground=t["text_muted"]).pack(side="right", padx=(0, 10))

        # ── Environment Section ─────────────────────────────────────────────
        env = ttk.LabelFrame(root, text=" Environment ", padding=10)
        env.pack(fill="x", pady=(0, 6))

        base_frame = ttk.Frame(env)
        base_frame.pack(fill="x", pady=(0, 4))
        ttk.Label(base_frame, text="Base URL *", font=("Segoe UI", 9, "bold"), foreground=t["text_primary"]).pack(side="left", padx=(0, 8))
        base_entry = ttk.Entry(base_frame, textvariable=self.env_vars["BASE_URL"])
        base_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Label(base_frame, text="* Only Base URL is required", font=("Segoe UI", 8, "italic"), foreground=t["text_muted"]).pack(side="left")

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

        # Track changes on env variables
        for var in self.env_vars.values():
            var.trace_add("write", lambda *_: self._on_modified())

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

        self.editor = tk.Text(
            editor_frame,
            height=12,
            wrap="none",
            font=("Consolas", 10),
            undo=True,
            bg=t["editor_bg"],
            fg=t["editor_fg"],
            insertbackground=t["editor_insert"],
            selectbackground=t["highlight_focus"],
            selectforeground=t["text_primary"],
            padx=6,
            pady=4,
        )
        self.line_numbers = LineNumbers(editor_frame, self.editor)
        self.line_numbers.set_colors(t["gutter_bg"], t["gutter_fg"])

        yscroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self._on_y_scroll)
        xscroll = ttk.Scrollbar(editor_frame, orient="horizontal", command=self.editor.xview)

        def _on_editor_scroll(*args: Any) -> None:
            yscroll.set(*args)
            if hasattr(self, "line_numbers"):
                self.line_numbers.redraw()

        self.editor.configure(yscrollcommand=_on_editor_scroll, xscrollcommand=xscroll.set)

        self.line_numbers.grid(row=0, column=0, sticky="ns")
        self.editor.grid(row=0, column=1, sticky="nsew")
        yscroll.grid(row=0, column=2, sticky="ns")
        xscroll.grid(row=1, column=1, sticky="ew")

        editor_frame.columnconfigure(1, weight=1)
        editor_frame.rowconfigure(0, weight=1)

        # Highlighting tag styles
        self._apply_editor_theme()

        script_actions = ttk.Frame(script_box)
        script_actions.pack(fill="x", pady=(6, 0))
        self.parse_button = ttk.Button(script_actions, text="Parse Tests", command=self.parse_script)
        self.parse_button.pack(side="left")
        ttk.Button(script_actions, text="Clear", command=lambda: (self.editor.delete("1.0", "end"), self._on_modified())).pack(side="left", padx=6)

        if self.controller.state.source:
            self.editor.insert("1.0", self.controller.state.source)

        self._mark_clean()
        self.editor.bind("<KeyRelease>", lambda _: (self._on_modified(), self.line_numbers.redraw()))
        self.editor.bind("<<Modified>>", self._on_text_modified)
        self.editor.bind("<Configure>", lambda _: self.line_numbers.redraw())

        # Right: Test Cases
        cases_box = ttk.LabelFrame(hpanes, text=" Test Cases ", padding=6)
        hpanes.add(cases_box, weight=1)

        run_controls = ttk.Frame(cases_box)
        run_controls.pack(fill="x", pady=(0, 4))
        self.run_selected_button = ttk.Button(run_controls, text="▶ Run Selected", style="Primary.TButton", command=lambda: self.start_run(True))
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

        self.tree.tag_configure("PASS", foreground=t["status_pass"])
        self.tree.tag_configure("FAIL", foreground=t["status_fail"])
        self.tree.tag_configure("ERROR", foreground=t["status_error"])
        self.tree.tag_configure("RUNNING", foreground=t["status_running"])
        self.tree.tag_configure("NOT_RUN", foreground=t["status_not_run"])

        progress_box = ttk.Frame(cases_box)
        progress_box.pack(fill="x", pady=(2, 0))
        self.bar = ttk.Progressbar(progress_box, mode="determinate")
        self.bar.pack(fill="x", pady=(0, 2))
        ttk.Label(progress_box, textvariable=self.progress, font=("Segoe UI", 8), foreground=t["text_secondary"]).pack(anchor="w")

        # Bottom: Result Detail
        results_box = ttk.LabelFrame(vpanes, text=" Result Detail ", padding=6)
        vpanes.add(results_box, weight=2)

        results_header = ttk.Frame(results_box)
        results_header.pack(fill="x", pady=(0, 4))
        ttk.Label(results_header, text="Inspection & Assertions", font=("Segoe UI", 9, "bold"), foreground=t["text_secondary"]).pack(side="left")
        ttk.Button(results_header, text="Clear View", command=self.clear_result_details).pack(side="right")

        detail_frame = ttk.Frame(results_box)
        detail_frame.pack(fill="both", expand=True)
        self.details = tk.Text(
            detail_frame,
            wrap="word",
            font=("Consolas", 10),
            state="disabled",
            bg=t["editor_bg"],
            fg=t["editor_fg"],
            insertbackground=t["editor_insert"],
            padx=8,
            pady=6,
        )
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.details.yview)
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

        self._apply_details_theme()

        # ── Footer ──────────────────────────────────────────────────────────
        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(6, 0))
        ttk.Label(footer, textvariable=self.summary, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(footer, text="Session History", command=self.show_history).pack(side="right", padx=5)
        ttk.Button(footer, text="Export CSV", command=lambda: self.export_report("csv")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export JSON", command=lambda: self.export_report("json")).pack(side="right", padx=3)
        ttk.Button(footer, text="Export HTML", command=lambda: self.export_report("html")).pack(side="right", padx=3)

        self.parse_script()

    def _on_y_scroll(self, *args: Any) -> None:
        self.editor.yview(*args)
        if hasattr(self, "line_numbers"):
            self.line_numbers.redraw()

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
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        for test in self.controller.state.tests:
            result = self.result_by_name.get(test.function_name)
            selected = "☑" if test.function_name in self.controller.state.selected else "☐"
            id_prefix = f"[{test.test_id}] " if test.test_id else ""
            title = f"{selected}  {id_prefix}{test.display_name}".strip()
            status_key = str(result.status) if result else "NOT_RUN"
            status = STATUS_MARK.get(status_key, status_key)
            duration = f"{result.duration_ms} ms" if result and result.duration_ms is not None else ""
            self.tree.insert("", "end", iid=test.function_name, values=(title, status, duration), tags=(status_key,))
        self._update_summary()
        self._update_code_highlighting(self.focused_function, scroll_to_focus=False)

    def _update_code_highlighting(self, focused_function: str | None = None, scroll_to_focus: bool = True) -> None:
        """Accurately highlight test functions in the Python script editor."""
        if not hasattr(self, "editor"):
            return

        self.editor.tag_remove("focused_test", "1.0", "end")
        self.editor.tag_remove("selected_test", "1.0", "end")

        tests_by_name = {t.function_name: t for t in self.controller.state.tests}

        # Apply secondary highlight to all selected tests
        for fn_name in self.controller.state.selected:
            if fn_name == focused_function:
                continue
            test = tests_by_name.get(fn_name)
            if test and test.start_line > 0 and test.end_line >= test.start_line:
                self.editor.tag_add("selected_test", f"{test.start_line}.0", f"{test.end_line}.end")

        # Apply primary focus highlight
        if focused_function:
            test = tests_by_name.get(focused_function)
            if test and test.start_line > 0 and test.end_line >= test.start_line:
                self.editor.tag_add("focused_test", f"{test.start_line}.0", f"{test.end_line}.end")
                if scroll_to_focus:
                    self.editor.see(f"{test.start_line}.0")

    def _toggle_or_details(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if not item:
            return

        col = self.tree.identify_column(event.x)
        self.focused_function = item

        if col == "#1":
            is_now_selected = item not in self.controller.state.selected
            self.controller.state.set_selected(item, is_now_selected)
            self._render_tests()
            self._update_code_highlighting(self.focused_function, scroll_to_focus=True)
        else:
            self._update_code_highlighting(self.focused_function, scroll_to_focus=True)

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
                    self.focused_function = value.function_name
                    self._update_code_highlighting(self.focused_function, scroll_to_focus=True)
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
            messagebox.showinfo("No results to export", "There's no test result data to export yet.", parent=self)
            return
        extension = report_type.lower()
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Export {extension.upper()} report",
            defaultextension=f".{extension}",
            filetypes=[(f"{extension.upper()} report", f"*.{extension}"), ("All files", "*.*")],
        )
        if not path:
            return
        generator = ReportGenerator(self.database, self._environment())
        try:
            getattr(generator, f"generate_{extension}_report")(session_id, path)
        except OSError as error:
            messagebox.showerror("Export failed", f"PostBaby could not save the report.\n\n{error}", parent=self)
            return
        self.status.set(f"✓ Report exported: {Path(path).name}")
        messagebox.showinfo("Report exported", f"Saved report to:\n{path}", parent=self)

    def show_recovery(self, sessions) -> None:
        lines = [f"Session #{s.id}: {s.completed_tests} / {s.total_tests} completed" for s in sessions]
        if messagebox.askyesno(
            "🍼 Welcome Back",
            "Looks like a test run was interrupted.\n\n" + "\n".join(lines) + "\n\nResume the most recent session?",
            parent=self,
        ):
            session = sessions[0]
            source = self.database.latest_script_snapshot(session.id)
            self.show_runner()
            if source:
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", source)
                self.parse_script()
            self.resume_session_id = session.id
            self.status.set(f"⏸ Ready to resume Session #{session.id}")

    def show_history(self) -> None:
        window = tk.Toplevel(self)
        window.title("PostBaby — Session History")
        window.geometry("700x400")

        t = self._theme()
        window.configure(bg=t["bg"])

        tree = ttk.Treeview(window, columns=("project", "progress", "status", "results"), show="headings")
        for key, title in (("project", "Project"), ("progress", "Progress"), ("status", "Status"), ("results", "Results")):
            tree.heading(key, text=title)
            tree.column(key, width=155)
        tree.pack(fill="both", expand=True, padx=12, pady=12)

        for row in self.database.session_history():
            tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["project_name"],
                    f"{row['completed_tests']} / {row['total_tests']}",
                    row["status"],
                    f"{row['passed']} PASS  {row['failed']} FAIL  {row['errors']} ERROR",
                ),
            )

        def view() -> None:
            selection = tree.selection()
            if not selection:
                return
            sid = int(selection[0])
            source = self.database.latest_script_snapshot(sid)
            session = self.database.get_session(sid)
            if session:
                proj = self.database.connection.execute("SELECT name FROM projects WHERE id=?", (session.project_id,)).fetchone()
                if proj:
                    self.project_name.set(proj["name"])
            self.show_runner()
            if source:
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", source)
                self.parse_script()
            for row in self.database.session_results(sid):
                self.result_by_name[row["function_name"]] = type("Result", (), dict(row))()
            self._render_tests()
            self._mark_clean()
            window.destroy()

        def export_selected(report_type: str) -> None:
            selection = tree.selection()
            if selection:
                self.export_report(report_type, int(selection[0]))

        controls = ttk.Frame(window)
        controls.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(controls, text="View Results", style="Primary.TButton", command=view).pack(side="left", padx=3)
        ttk.Button(controls, text="Export HTML", command=lambda: export_selected("html")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export JSON", command=lambda: export_selected("json")).pack(side="left", padx=3)
        ttk.Button(controls, text="Export CSV", command=lambda: export_selected("csv")).pack(side="left", padx=3)
        ttk.Button(controls, text="Close", command=window.destroy).pack(side="right")

    def destroy(self) -> None:
        self._destroyed = True
        if hasattr(self, "_drain_job"):
            try:
                self.after_cancel(self._drain_job)
            except Exception:
                pass
        try:
            self.eval("foreach id [after info] {after cancel $id}")
        except Exception:
            pass
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
