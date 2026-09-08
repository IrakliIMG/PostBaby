"""Portable, local report exports based solely on persisted PostBaby data."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .database import Database
from .security import SecretRedactor


class ReportGenerator:
    def __init__(self, database: Database, secrets: Mapping[str, str | None] | None = None) -> None:
        self.database = database
        self.redactor = SecretRedactor(secrets)

    def report_data(self, session_id: int) -> dict:
        session = self.database.connection.execute(
            """SELECT s.*, p.name AS project FROM sessions s JOIN projects p ON p.id=s.project_id WHERE s.id=?""", (session_id,)
        ).fetchone()
        if not session:
            raise ValueError(f"Session #{session_id} does not exist")
        names = {row["function_name"]: row for row in self.database.connection.execute(
            "SELECT function_name, test_id, display_name FROM test_runs WHERE session_id=?", (session_id,)
        )}
        rows = self.database.session_results(session_id)
        tests = []
        for row in rows:
            name = names.get(row["function_name"])
            tests.append({
                "id": row["test_id"] or (name["test_id"] if name else None),
                "name": name["display_name"] if name else row["function_name"], "function_name": row["function_name"],
                "status": row["status"], "duration_ms": row["duration_ms"], "started_at": row["started_at"], "finished_at": row["completed_at"],
                "http_method": self.redactor.redact(row["http_method"]), "url": self.redactor.redact(row["url"]),
                "http_status": row["http_status"], "error": self.redactor.redact(row["error_message"]),
                "details": self.redactor.redact(row["details"]), "response_body": self.redactor.redact(row["response_body"]),
                "stdout": self.redactor.redact(row["stdout"]), "stderr": self.redactor.redact(row["stderr"]),
            })
        statuses = [test["status"] for test in tests]
        summary = {"total": session["total_tests"], "completed": session["completed_tests"], "passed": statuses.count("PASS"),
                   "failed": statuses.count("FAIL"), "errors": statuses.count("ERROR"), "skipped": statuses.count("SKIPPED"),
                   "interrupted": statuses.count("INTERRUPTED")}
        duration = sum(test["duration_ms"] or 0 for test in tests)
        return {"application": "PostBaby", "project": session["project"],
                "session": {"id": session["id"], "status": session["status"], "started_at": session["created_at"],
                            "finished_at": session["updated_at"], "duration_ms": duration}, "summary": summary, "tests": tests}

    def generate_json_report(self, session_id: int, output_path: str | Path) -> Path:
        target = Path(output_path); target.write_text(json.dumps(self.report_data(session_id), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def generate_csv_report(self, session_id: int, output_path: str | Path) -> Path:
        target, data = Path(output_path), self.report_data(session_id)
        headers = ["Test ID", "Test Name", "Status", "Duration (ms)", "HTTP Method", "URL", "HTTP Status", "Error", "Assertion", "Started At", "Finished At"]
        with target.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers); writer.writeheader()
            for test in data["tests"]:
                writer.writerow({"Test ID": _csv_safe(test["id"]), "Test Name": _csv_safe(test["name"]), "Status": test["status"],
                    "Duration (ms)": test["duration_ms"], "HTTP Method": _csv_safe(test["http_method"]), "URL": _csv_safe(test["url"]),
                    "HTTP Status": test["http_status"], "Error": _csv_safe(test["error"]), "Assertion": _csv_safe(test["details"]),
                    "Started At": test["started_at"], "Finished At": test["finished_at"]})
        return target

    def generate_html_report(self, session_id: int, output_path: str | Path) -> Path:
        target, data = Path(output_path), self.report_data(session_id)
        summary = data["summary"]
        cards = "".join(_test_html(test) for test in data["tests"]) or "<p class='empty'>No test result data is available for this session.</p>"
        counters = "".join(f"<div><b>{summary[key]}</b><span>{label}</span></div>" for key, label in (("total", "Tests"), ("passed", "Pass"), ("failed", "Fail"), ("errors", "Error"), ("skipped", "Skipped"), ("interrupted", "Interrupted")))
        session = data["session"]
        page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>PostBaby Report #{session['id']}</title>
<style>body{{font:15px Segoe UI,Arial,sans-serif;max-width:1050px;margin:36px auto;color:#25313c;background:#fafbfc}}header{{border-bottom:3px solid #f0a66a;padding-bottom:18px}}h1{{margin:0}}.muted{{color:#667784}}.summary{{display:flex;gap:12px;flex-wrap:wrap;margin:25px 0}}.summary div{{background:white;border:1px solid #dbe3e8;border-radius:8px;padding:13px;min-width:82px}}.summary b{{display:block;font-size:22px}}.summary span{{color:#667784}}.test{{background:white;border:1px solid #dbe3e8;border-left:5px solid #73808b;border-radius:7px;padding:16px;margin:12px 0}}.PASS{{border-left-color:#32855c}}.FAIL{{border-left-color:#c14646}}.ERROR{{border-left-color:#bc7a22}}.meta{{display:grid;grid-template-columns:160px 1fr;gap:5px 12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:10px;border-radius:4px}}.status{{font-weight:bold}}.empty{{padding:18px;background:white}}</style></head><body>
<header><h1>🍼 POSTBABY</h1><h2>API Test Report</h2><p><b>Project:</b> {html.escape(data['project'])}<br><b>Session:</b> #{session['id']} · {html.escape(session['status'])}<br><b>Date:</b> {html.escape(session['started_at'])}<br><b>Total duration:</b> {_duration(session['duration_ms'])}</p></header>
<h2>Summary</h2><section class='summary'>{counters}</section><h2>Test Results</h2>{cards}</body></html>"""
        target.write_text(page, encoding="utf-8")
        return target


def _test_html(test: dict) -> str:
    fields = [("HTTP", " ".join(str(x) for x in (test["http_method"], test["url"], test["http_status"]) if x)),
              ("Error", test["error"]), ("Assertion", test["details"]), ("Response", test["response_body"]), ("Stdout", test["stdout"]), ("Stderr", test["stderr"])]
    detail = "".join(f"<dt>{html.escape(label)}</dt><dd><pre>{html.escape(str(value))}</pre></dd>" for label, value in fields if value)
    return f"<article class='test {html.escape(test['status'])}'><h3>{html.escape(test['id'] or test['name'])}</h3><p>{html.escape(test['name'])}</p><div class='meta'><b>Status</b><span class='status'>{html.escape(test['status'])}</span><b>Duration</b><span>{_duration(test['duration_ms'])}</span></div><dl>{detail}</dl></article>"


def _duration(milliseconds: int | None) -> str:
    return f"{(milliseconds or 0) / 1000:.3f} s"


def _csv_safe(value: object | None) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in "=+-@" else text
