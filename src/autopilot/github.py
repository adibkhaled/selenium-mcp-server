from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .reporting import TestResult, load_test_result


class GitHubError(RuntimeError):
    """GitHub API request failed or was rejected."""


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMMENT_MARKER = "<!-- selenium-autopilot-report -->"
_MAX_BODY_BYTES = 60_000


@dataclass(frozen=True)
class GitHubSettings:
    repository: str
    pull_request: int
    token: str
    api_url: str = "https://api.github.com"
    run_url: str | None = None
    timeout: float = 20.0

    def __post_init__(self) -> None:
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository must be in owner/repo format.")
        if self.pull_request <= 0:
            raise ValueError("pull_request must be a positive number.")
        if not self.token.strip():
            raise ValueError("GitHub token must not be empty.")
        parsed = urlparse(self.api_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("GitHub API must use HTTPS except for a local test endpoint.")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("api_url must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("api_url must not contain credentials, query parameters, or fragments.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("GitHub API timeout must be a finite number greater than zero.")


class GitHubAPI:
    def __init__(self, settings: GitHubSettings) -> None:
        self.settings = settings
        self.api_url = settings.api_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, object] | None = None):
        url = f"{self.api_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.settings.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "selenium-autopilot",
            },
        )
        try:
            with urlopen(request, timeout=self.settings.timeout) as response:
                data = response.read()
                parsed = json.loads(data.decode("utf-8")) if data else None
                return parsed, response.headers
        except HTTPError as exc:
            detail = ""
            try:
                error = json.loads(exc.read().decode("utf-8"))
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = f" {error['message'][:300]}"
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
            raise GitHubError(f"GitHub API returned HTTP {exc.code}.{detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"Could not reach GitHub API: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GitHubError("GitHub API returned malformed JSON.") from exc

    def _comments(self) -> list[dict[str, object]]:
        base_path = (
            f"/repos/{self.settings.repository}/issues/"
            f"{self.settings.pull_request}/comments?per_page=100"
        )
        payload, headers = self.request("GET", base_path)
        if not isinstance(payload, list):
            raise GitHubError("GitHub comments response was not a list.")
        comments = [item for item in payload if isinstance(item, dict)]
        link_header = headers.get("Link", "")
        next_url = _next_link(link_header)
        while next_url:
            parsed = urlparse(next_url)
            expected = urlparse(self.api_url)
            if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
                raise GitHubError("GitHub pagination link points outside the configured API host.")
            api_prefix = expected.path.rstrip("/")
            if api_prefix and not parsed.path.startswith(f"{api_prefix}/"):
                raise GitHubError("GitHub pagination link points outside the configured API path.")
            relative_path = parsed.path[len(api_prefix):] if api_prefix else parsed.path
            payload, headers = self.request(
                "GET",
                relative_path + (f"?{parsed.query}" if parsed.query else ""),
            )
            if not isinstance(payload, list):
                raise GitHubError("GitHub comments pagination response was not a list.")
            comments.extend(item for item in payload if isinstance(item, dict))
            next_url = _next_link(headers.get("Link", ""))
        return comments

    def publish_test_report(
        self,
        report: TestResult,
        workflow_status: str | None = None,
    ) -> str:
        body = format_pull_request_comment(
            report,
            self.settings.run_url,
            workflow_status,
        )
        if len(body.encode("utf-8")) > _MAX_BODY_BYTES:
            raise GitHubError("Formatted report comment exceeds the GitHub comment size limit.")
        path = (
            f"/repos/{self.settings.repository}/issues/"
            f"{self.settings.pull_request}/comments"
        )
        for comment in self._comments():
            if _COMMENT_MARKER in str(comment.get("body", "")):
                comment_url = comment.get("url")
                if not isinstance(comment_url, str):
                    raise GitHubError("Existing report comment has an invalid API URL.")
                parsed_comment_url = urlparse(comment_url)
                parsed_api_url = urlparse(self.api_url)
                expected_prefix = (
                    f"{parsed_api_url.path.rstrip('/')}/repos/"
                    f"{self.settings.repository}/issues/comments/"
                )
                if (
                    parsed_comment_url.scheme != parsed_api_url.scheme
                    or parsed_comment_url.netloc != parsed_api_url.netloc
                    or not parsed_comment_url.path.startswith(expected_prefix)
                ):
                    raise GitHubError("Existing report comment has an invalid API URL.")
                comment_id = comment_url.rsplit("/", 1)[-1]
                if not comment_id.isdigit():
                    raise GitHubError("Existing report comment ID is invalid.")
                self.request(
                    "PATCH",
                    f"/repos/{self.settings.repository}/issues/comments/{comment_id}",
                    {"body": body},
                )
                return "updated"
        self.request("POST", path, {"body": body})
        return "created"


def _next_link(header: str) -> str | None:
    for entry in header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="next"\s*$', entry.strip())
        if match:
            return match.group(1)
    return None


def _markdown_text(value: str, limit: int = 180) -> str:
    cleaned = "".join(
        character for character in value if character.isprintable() or character in "\t"
    )
    cleaned = (
        cleaned.replace("`", "'")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned or "(unnamed test)"


def format_pull_request_comment(
    report: TestResult,
    run_url: str | None,
    workflow_status: str | None = None,
) -> str:
    if workflow_status == "failure":
        status = "❌ Workflow failed"
    elif workflow_status == "cancelled":
        status = "⚠️ Workflow cancelled"
    elif workflow_status == "skipped":
        status = "⚠️ Test job skipped"
    elif report.source == "unavailable":
        status = "⚠️ Results unavailable"
    elif report.total == 0:
        status = "⚠️ No test cases reported"
    elif workflow_status == "success":
        status = (
            "✅ Workflow succeeded"
            if report.failed == 0 and report.errors == 0
            else "❌ Test results failed"
        )
    else:
        status = "❌ Test results failed" if report.failed > 0 or report.errors > 0 else "✅ Passed"
    lines = [
        _COMMENT_MARKER,
        "## Selenium Autopilot test report",
        "",
        f"**Status:** {status}",
        (
            f"**JUnit summary:** {report.passed} passed · {report.failed} failed · "
            f"{report.errors} errors · {report.skipped} skipped "
            f"({report.total} total, {report.duration_seconds:.2f}s)"
        ),
    ]
    if report.source == "unavailable":
        lines.extend(("", "The test job did not produce a JUnit report. Check the workflow run for setup failures."))
    if report.failures:
        lines.extend(("", "### Failed tests"))
        for failure in report.failures[:20]:
            lines.append(
                f"- `{_markdown_text(failure.nodeid, 300)}` — "
                f"{_markdown_text(failure.outcome)}"
            )
        if len(report.failures) > 20:
            lines.append(f"- …and {len(report.failures) - 20} more failures.")
    lines.extend(
        (
            "",
            "Failure details and diagnostics are available in the workflow artifacts.",
            "",
            f"[View workflow run]({_safe_run_url(run_url)})"
            if run_url
            else "Workflow run link unavailable.",
            "",
            (
                f"_Workflow job status: `{_markdown_text(workflow_status)}`. "
                "Test counts are parsed from the JUnit artifact._"
                if workflow_status
                else "_Test counts are parsed from the JUnit report._"
            ),
            "_This report does not apply or validate code repairs._",
        )
    )
    return "\n".join(lines)


def _safe_run_url(run_url: str) -> str:
    parsed = urlparse(run_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not re.fullmatch(r"https://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+", run_url)
    ):
        raise ValueError("run_url must be a safe HTTPS URL.")
    return run_url


def publish_report(
    settings: GitHubSettings,
    report_path: str,
    workflow_status: str | None = None,
) -> str:
    report = load_test_result(report_path)
    return GitHubAPI(settings).publish_test_report(report, workflow_status)
