from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

import pytest

from autopilot.github import (
    GitHubAPI,
    GitHubError,
    GitHubSettings,
    format_pull_request_comment,
)
from autopilot.reporting import ReportError, load_test_result, parse_junit_xml
from autopilot.reporting import TestFailure as AutopilotTestFailure
from autopilot.reporting import TestResult as AutopilotTestResult


def _http_response(payload, headers: dict[str, str] | None = None):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = (
        json.dumps(payload).encode("utf-8") if payload is not None else b""
    )
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    response.headers = message
    return response


def _test_result():
    junit = """<?xml version="1.0"?>
    <testsuites tests="3" failures="1" errors="0" skipped="1" time="1.25">
      <testsuite>
        <testcase classname="tests.test_login" name="test_success" time="0.5"/>
        <testcase classname="tests.test_login" name="test_failure" time="0.5">
          <failure message="assertion failed">full stack trace with private data</failure>
        </testcase>
        <testcase classname="tests.test_login" name="test_skipped" time="0.25">
          <skipped message="not configured"/>
        </testcase>
      </testsuite>
    </testsuites>
    """
    return junit


def test_junit_report_becomes_machine_readable_summary(tmp_path: Path):
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(_test_result(), encoding="utf-8")

    report = parse_junit_xml(junit_path)

    assert report.total == 3
    assert report.passed == 1
    assert report.failed == 1
    assert report.errors == 0
    assert report.skipped == 1
    assert report.duration_seconds == 1.25
    assert report.failures[0].nodeid == "tests.test_login::test_failure"
    assert report.to_dict()["schema_version"] == "1.0"


def test_junit_report_rejects_doctype_malformed_xml_and_oversized_input(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text("<!DOCTYPE x [<!ENTITY e 'x'>]><testsuite/>", encoding="utf-8")
    with pytest.raises(ReportError, match="must not declare DTDs"):
        parse_junit_xml(path)

    path.write_text("<testsuite>", encoding="utf-8")
    with pytest.raises(ReportError, match="not valid XML"):
        parse_junit_xml(path)

    path.write_bytes(b" " * 5_000_001)
    with pytest.raises(ReportError, match="exceeds"):
        parse_junit_xml(path)


def test_load_test_result_checks_counts_and_entries(tmp_path: Path):
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(_test_result(), encoding="utf-8")
    result = parse_junit_xml(junit_path)
    report_path = tmp_path / "result.json"
    report_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

    assert load_test_result(report_path) == result

    malformed = result.to_dict()
    malformed["summary"]["total"] = 500
    report_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ReportError, match="do not add up"):
        load_test_result(report_path)


def test_pull_request_comment_is_idempotent_and_does_not_publish_traceback(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if request.method == "GET":
            return _http_response([])
        return _http_response({"id": 123})

    monkeypatch.setattr("autopilot.github.urlopen", fake_urlopen)
    result = parse_junit_xml_from_string(_test_result())
    settings = GitHubSettings(
        repository="owner/repo",
        pull_request=42,
        token="secret-token",
        run_url="https://github.com/owner/repo/actions/runs/99",
    )

    action = GitHubAPI(settings).publish_test_report(result)

    assert action == "created"
    assert [request.method for request, _ in calls] == ["GET", "POST"]
    posted_body = json.loads(calls[-1][0].data.decode("utf-8"))["body"]
    assert "<!-- selenium-autopilot-report -->" in posted_body
    assert "test_failure" in posted_body
    assert "full stack trace" not in posted_body
    assert "secret" not in posted_body
    assert calls[-1][0].get_header("Authorization") == "Bearer secret-token"
    assert calls[-1][1] == 20.0


def test_pull_request_report_updates_its_existing_comment(monkeypatch):
    calls = []
    api_url = "https://api.github.com"

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 20.0
        if request.method == "GET":
            return _http_response(
                [
                    {
                        "body": "<!-- selenium-autopilot-report --> old",
                        "url": f"{api_url}/repos/owner/repo/issues/comments/321",
                    }
                ]
            )
        return _http_response({"id": 321})

    monkeypatch.setattr("autopilot.github.urlopen", fake_urlopen)
    result = parse_junit_xml_from_string(_test_result())

    assert GitHubAPI(
        GitHubSettings("owner/repo", 42, "token")
    ).publish_test_report(result) == "updated"
    assert [request.method for request in calls] == ["GET", "PATCH"]
    assert calls[-1].full_url.endswith("/issues/comments/321")


def test_pagination_refuses_external_host_before_sending_token(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 20.0
        if request.method == "GET":
            return _http_response(
                [],
                {"Link": '<https://evil.example/comments?page=2>; rel="next"'},
            )
        raise AssertionError("external page must not be fetched")

    monkeypatch.setattr("autopilot.github.urlopen", fake_urlopen)

    with pytest.raises(GitHubError, match="outside the configured API host"):
        GitHubAPI(GitHubSettings("owner/repo", 42, "token")).publish_test_report(
            parse_junit_xml_from_string(_test_result())
        )
    assert len(calls) == 1


def test_settings_and_markdown_output_validation():
    with pytest.raises(ValueError, match="owner/repo"):
        GitHubSettings("owner/repo/path", 1, "token")
    with pytest.raises(ValueError, match="HTTPS"):
        GitHubSettings(
            "owner/repo",
            1,
            "token",
            api_url="http://github.example.com/api/v3",
        )


def test_workflow_status_overrides_untrusted_junit_status():
    passed = AutopilotTestResult(
        total=1,
        passed=1,
        failed=0,
        errors=0,
        skipped=0,
        duration_seconds=0.1,
        failures=(),
    )
    comment = format_pull_request_comment(
        passed,
        "https://github.com/owner/repo/actions/runs/99",
        "failure",
    )
    assert "**Status:** ❌ Workflow failed" in comment
    assert "JUnit summary" in comment

    unavailable = AutopilotTestResult(
        total=0,
        passed=0,
        failed=0,
        errors=0,
        skipped=0,
        duration_seconds=0,
        failures=(),
        source="unavailable",
    )
    assert "Results unavailable" in format_pull_request_comment(unavailable, None, "success")


def test_comment_escaping_prevents_markdown_injection():
    report = AutopilotTestResult(
        total=1,
        passed=0,
        failed=1,
        errors=0,
        skipped=0,
        duration_seconds=0.1,
        failures=(
            AutopilotTestFailure("test_<script>`(https://evil.test)", "failed", "error | hidden"),
        ),
    )
    comment = format_pull_request_comment(report, None)

    assert "`test_&lt;script&gt;'(https://evil.test)`" in comment
    assert "error |" not in comment
    with pytest.raises(ValueError, match="safe HTTPS URL"):
        format_pull_request_comment(
            parse_junit_xml_from_string(_test_result()),
            "https://github.com/owner/repo/actions/runs/1) bad",
        )


def parse_junit_xml_from_string(content: str):
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".xml",
        delete=False,
    ) as junit:
        junit.write(content)
        path = Path(junit.name)
    try:
        return parse_junit_xml(path)
    finally:
        path.unlink(missing_ok=True)
