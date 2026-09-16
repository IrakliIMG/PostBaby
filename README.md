# PostBaby 🍼

PostBaby is a lightweight local Windows desktop API-test runner for Python scripts generated with an LLM. It is not a Postman clone and does not connect to an AI service: use your preferred LLM separately, then paste the resulting test script into PostBaby.

## Current status (v2.0.0)

This repository contains a local Tkinter desktop application plus its execution core: AST-only script discovery and validation, runtime environment substitution, secret redaction, isolated per-test execution, SQLite-backed sessions/resume, and HTML, JSON, and CSV report exports. v2.0.0 introduces Script Contract 2.0 (expanded standard library support with runtime defense-in-depth), flexible environment variable substitution, and a refined Clam-styled QA interface.

## Run PostBaby

```bash
python3 -m postbaby.app
```

PostBaby uses the Python standard-library `tkinter` module. It is included with normal Windows Python installers; on some Linux distributions it must be installed separately as the distribution's `python3-tk` package.

The welcome screen copies the built-in LLM prompt to your clipboard. The test-runner screen accepts a project name, environment values, and a Python script; parsing never executes the script. Runs execute in a background thread so the interface remains responsive, and every completed result is saved immediately.

## Reports

After a session has test results, use **Export HTML**, **Export JSON**, or **Export CSV** in the runner footer. Session History provides the same export choices for a selected historical session. Reports are generated from the persisted session data and contain redacted captured output. HTML reports are standalone; JSON and CSV support further QA analysis.

## Run the internal tests

Requires Python 3.11+ (the application uses only the standard library in Phase 1):

```bash
python -m unittest discover -s tests -v
```

## Script contract

Scripts use Python 3 and may import `requests` plus selected standard-library modules. Each executable test is an independent top-level function named `test_*`, uses ordinary `assert` statements, and must not use pytest, unittest, subprocesses, shell commands, arbitrary file access, or OS operations. Discovery is AST based and does not execute the script.

Use `{{BASE_URL}}` rather than a literal service URL. The supported runtime variables planned for the runner are `{{BASE_URL}}`, `{{TOKEN}}`, `{{API_KEY}}`, `{{USERNAME}}`, `{{PASSWORD}}`, `{{CLIENT_ID}}`, and `{{CLIENT_SECRET}}`. Never hardcode credentials.

See [samples/example_api_tests.py](samples/example_api_tests.py) for a paste-ready example.

## Persistence, execution, and recovery

`postbaby.db` is created automatically when the application starts. The schema contains projects, sessions, script snapshots, test runs, results, and settings. It has no plaintext-secret field; session metadata only records the base URL. A `RUNNING` marker is committed before each test and its final result is committed immediately afterwards. Startup recovery marks sessions left in `RUNNING` state as `INTERRUPTED` and makes unfinished tests eligible for resume.

The execution core runs only the selected function plus its imports, captures stdout/stderr and ordinary `requests` request information where available, and redacts configured password/token/API-key/client-secret values before returning or storing captured content. It is controlled execution for the PostBaby script contract, not a security sandbox for untrusted code.

## Future Windows packaging

User-generated scripts are executed according to the PostBaby script contract. This controlled execution is not a hardened security sandbox against malicious Python. A later packaging phase can create a Windows executable with PyInstaller, keeping the SQLite database in an appropriate user-data directory.

## Windows packaging

Build on Windows with Python 3.11+ installed. From the project root, run:

```bat
build_windows.bat
```

The script creates a local `.venv`, installs `requests` and PyInstaller, runs the full test suite, then produces `dist\PostBaby\PostBaby.exe`. Distribute the entire `dist\PostBaby` folder, not the executable alone.

The packaged application stores `postbaby.db` in `%LOCALAPPDATA%\PostBaby` (falling back to `%APPDATA%` where needed), independent of the executable's install location. Existing development databases in the launch directory are retained rather than deleted. Reports remain user-selected files through the save dialog.
