from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class ReportError(ValueError):
    """A test report could not be read or normalized."""


@dataclass(frozen=True)
class TestFailure:
    nodeid: str
    outcome: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "nodeid": self.nodeid,
            "outcome": self.outcome,
            "message": self.message,
        }


@dataclass(frozen=True)
class TestResult:
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    failures: tuple[TestFailure, ...]
    source: str = "junit"
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "skipped": self.skipped,
                "duration_seconds": self.duration_seconds,
            },
            "failures": [failure.to_dict() for failure in self.failures],
        }


_NODE_NAME = re.compile(r"^[A-Za-z0-9_./:[\]@= -]{1,500}$")
_MAX_JUNIT_BYTES = 5_000_000
_MAX_FAILURES = 100
_MAX_MESSAGE_LENGTH = 4_000


def parse_junit_xml(path: str | Path) -> TestResult:
    report_path = Path(path)
    try:
        if report_path.stat().st_size > _MAX_JUNIT_BYTES:
            raise ReportError(f"JUnit report exceeds the {_MAX_JUNIT_BYTES}-byte limit.")
        content = report_path.read_bytes()
    except ReportError:
        raise
    except OSError as exc:
        raise ReportError(f"Could not read JUnit report {report_path}: {exc}") from exc

    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ReportError("JUnit report must not declare DTDs or entities.")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ReportError(f"JUnit report is not valid XML: {exc}") from exc

    cases = list(root.iter("testcase"))
    failures: list[TestFailure] = []
    passed = failed = errors = skipped = 0
    total_duration = 0.0
    for case in cases:
        name = case.get("name", "unnamed test")
        classname = case.get("classname", "")
        nodeid = f"{classname}::{name}" if classname else name
        if not _NODE_NAME.fullmatch(nodeid):
            nodeid = "test name omitted (contains unsupported characters)"
        try:
            duration = float(case.get("time", "0"))
            if math.isfinite(duration):
                total_duration += max(0.0, duration)
        except ValueError:
            pass

        failure = case.find("failure")
        error = case.find("error")
        skipped_element = case.find("skipped")
        if failure is not None:
            failed += 1
            _append_failure(failures, nodeid, "failed", failure)
        elif error is not None:
            errors += 1
            _append_failure(failures, nodeid, "error", error)
        elif skipped_element is not None:
            skipped += 1
        else:
            passed += 1

    return TestResult(
        total=len(cases),
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_seconds=round(total_duration, 3),
        failures=tuple(failures),
    )


def _append_failure(
    failures: list[TestFailure],
    nodeid: str,
    outcome: str,
    element: ET.Element,
) -> None:
    if len(failures) >= _MAX_FAILURES:
        return
    message = element.get("message") or (element.text or "").strip() or "No failure details."
    message = re.sub(r"\s+", " ", message)[:_MAX_MESSAGE_LENGTH]
    failures.append(TestFailure(nodeid, outcome, message))


def load_test_result(path: str | Path) -> TestResult:
    try:
        report_path = Path(path)
        if report_path.stat().st_size > _MAX_JUNIT_BYTES:
            raise ReportError(f"JSON test report exceeds the {_MAX_JUNIT_BYTES}-byte limit.")
        value = json.loads(report_path.read_text(encoding="utf-8"))
    except ReportError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"Could not read JSON test report {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ReportError("Test report must be a version 1.0 JSON object.")
    if set(value) != {"schema_version", "source", "summary", "failures"}:
        raise ReportError("Test report contains missing or unknown top-level fields.")
    summary = value.get("summary")
    failures = value.get("failures")
    if not isinstance(summary, dict) or not isinstance(failures, list):
        raise ReportError("Test report must contain summary and failures.")
    if set(summary) != {
        "total",
        "passed",
        "failed",
        "errors",
        "skipped",
        "duration_seconds",
    }:
        raise ReportError("Test report summary contains missing or unknown fields.")
    integer_counts = ("total", "passed", "failed", "errors", "skipped")
    counts: dict[str, int] = {}
    for key in integer_counts:
        item = summary.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ReportError(f"Test report summary field {key!r} must be a non-negative integer.")
        counts[key] = item
    duration = summary.get("duration_seconds")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ReportError("Test report duration_seconds must be a non-negative number.")
    if sum(counts[key] for key in ("passed", "failed", "errors", "skipped")) != counts["total"]:
        raise ReportError("Test report counts do not add up to total.")
    normalized_failures: list[TestFailure] = []
    for index, failure in enumerate(failures):
        if not isinstance(failure, dict):
            raise ReportError(f"failures[{index}] must be an object.")
        nodeid, outcome, message = (
            failure.get("nodeid"),
            failure.get("outcome"),
            failure.get("message"),
        )
        if not all(isinstance(item, str) and item for item in (nodeid, outcome, message)):
            raise ReportError(f"failures[{index}] requires nodeid, outcome, and message.")
        if outcome not in {"failed", "error"}:
            raise ReportError(f"failures[{index}].outcome must be failed or error.")
        normalized_failures.append(TestFailure(nodeid, outcome, message[:_MAX_MESSAGE_LENGTH]))
    if counts["failed"] + counts["errors"] != len(normalized_failures):
        raise ReportError("Failure entries must account for each failed test and test error.")
    source = value.get("source", "json")
    if not isinstance(source, str) or source not in {"junit", "unavailable"}:
        raise ReportError("Test report source must be 'junit' or 'unavailable'.")
    return TestResult(
        **counts,
        duration_seconds=float(duration),
        failures=tuple(normalized_failures),
        source=source,
    )
