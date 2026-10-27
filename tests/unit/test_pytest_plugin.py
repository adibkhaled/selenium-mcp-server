from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from autopilot.diagnostics import DiagnosticsReport
from autopilot import pytest_plugin


def _run_hook(monkeypatch, item, call, report):
    class Outcome:
        def get_result(self):
            return report

    hook = pytest_plugin.pytest_runtest_makereport(item, call)
    assert next(hook) is None
    try:
        hook.send(Outcome())
    except StopIteration:
        pass


def test_failure_hook_writes_browser_diagnostics_and_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "browser": "chrome",
                "browser_version": "123",
                "url": "https://test.example/login",
                "failed_action": "pytest call failed",
            }
        ),
        encoding="utf-8",
    )
    expected_report = DiagnosticsReport(
        screenshot=str(tmp_path / "failure.png"),
        dom_snapshot=str(tmp_path / "failure.html"),
        metadata=str(metadata),
        errors=(),
    )
    monkeypatch.setattr(
        pytest_plugin,
        "capture_diagnostics",
        lambda *_args, **_kwargs: expected_report,
    )
    driver = object()
    item = SimpleNamespace(
        funcargs={"driver": driver},
        nodeid="tests/test_login.py::test_login",
        path=Path("tests/test_login.py"),
        name="test_login",
    )
    call = SimpleNamespace(excinfo=SimpleNamespace(value=AssertionError("expected heading")))
    report = SimpleNamespace(
        when="call",
        failed=True,
        longrepr="assertion traceback",
    )

    _run_hook(monkeypatch, item, call, report)

    report_path = (
        tmp_path
        / "artifacts"
        / "diagnostics"
        / "tests_test_login.py_test_login"
        / "failure-report.json"
    )
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["exception_type"] == "AssertionError"
    assert saved["test_name"] == "test_login"
    assert saved["browser"] == "chrome"
    assert saved["url"] == "https://test.example/login"
    assert saved["screenshot"] == expected_report.screenshot


def test_failure_hook_skips_tests_without_driver(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ARTIFACTS_DIR", str(tmp_path))
    item = SimpleNamespace(funcargs={}, nodeid="tests/test_unit.py::test_value")
    call = SimpleNamespace(excinfo=None)
    report = SimpleNamespace(when="call", failed=True, longrepr="trace")

    _run_hook(monkeypatch, item, call, report)

    assert list(tmp_path.iterdir()) == []
