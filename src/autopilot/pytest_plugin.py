from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import pytest

from .diagnostics import capture_diagnostics
from .healing import FailureReport


logger = logging.getLogger(__name__)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    driver = item.funcargs.get("driver")
    if driver is None:
        return

    output_root = Path(os.environ.get("AUTOPILOT_ARTIFACTS_DIR", "artifacts"))
    safe_node_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.nodeid).strip("_")[:150]
    output_dir = output_root / "diagnostics" / (safe_node_id or "failed-test")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        diagnostics = capture_diagnostics(
            driver,
            output_dir,
            failed_action=f"pytest call failed: {item.nodeid}",
        )
        failure = FailureReport.from_diagnostics(
            diagnostics,
            call.excinfo.value if call.excinfo else AssertionError("Test failed."),
            traceback=str(report.longrepr),
            test_file=str(item.path),
            test_name=item.name,
        )
        failure_path = output_dir / "failure-report.json"
        failure_path.write_text(
            json.dumps(failure.to_dict(), indent=2),
            encoding="utf-8",
        )
        for error in diagnostics.errors:
            logger.warning("Could not collect Selenium diagnostics for %s: %s", item.nodeid, error)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("Could not save Selenium diagnostics for %s: %s", item.nodeid, exc)
