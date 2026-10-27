from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from selenium.common.exceptions import WebDriverException

from autopilot import Autopilot, AutopilotConfig
from autopilot.generation import TestGenerator as AutopilotTestGenerator
from autopilot.healing import (
    FailureAnalyzer,
    FailureCategory,
    FailureReport,
    propose_locator_healing,
)
from autopilot.planning import TestPlanner as AutopilotTestPlanner
from autopilot.reporting import parse_junit_xml


pytestmark = pytest.mark.integration

_PLAN_RESPONSE = {
    "schema_version": "1.0",
    "summary": "The home page displays its heading.",
    "scenarios": [
        {
            "id": "home-heading",
            "title": "Show the home page heading",
            "priority": "high",
            "category": "positive",
            "preconditions": [],
            "steps": ["Open the approved home page."],
            "expected": ["The Example home heading is visible."],
        }
    ],
    "ambiguities": [],
    "risks": [],
}
_GENERATION_RESPONSE = {
    "files": [
        {
            "path": "pages/home_page.py",
            "content": (
                "from selenium.webdriver.common.by import By\n\n"
                "class HomePage:\n"
                "    def __init__(self, driver):\n"
                "        self.driver = driver\n\n"
                "    def open(self):\n"
                "        self.driver.get('https://example.test/')\n\n"
                "    def heading(self):\n"
                "        return self.driver.find_element(By.TAG_NAME, 'h1').text\n"
            ),
        },
        {
            "path": "tests/test_home_page.py",
            "content": (
                "from pages.home_page import HomePage\n\n"
                "def test_home_page_heading(driver):\n"
                "    page = HomePage(driver)\n"
                "    page.open()\n"
                "    assert page.heading() == 'Example home'\n"
                "    assert driver.current_url == 'https://example.test/'\n"
            ),
        },
    ],
    "notes": [],
}


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_requirements_generate_execute_and_report_pytest_project(tmp_path: Path):
    requirements = (
        "When a user opens the approved home page, the Example home heading is visible."
    )
    plan = AutopilotTestPlanner(FakeProvider(json.dumps(_PLAN_RESPONSE))).create_plan(
        requirements
    )
    assert plan.scenarios[0].id == "home-heading"

    project_dir = tmp_path / "generated"
    AutopilotTestGenerator(FakeProvider(json.dumps(_GENERATION_RESPONSE))).generate(
        plan,
        project_dir,
    )
    (project_dir / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "from selenium.webdriver.common.by import By\n\n"
        "class FakeElement:\n"
        "    text = 'Example home'\n\n"
        "class FakeDriver:\n"
        "    current_url = ''\n"
        "    def get(self, url):\n"
        "        self.current_url = url\n"
        "    def find_element(self, by, value):\n"
        "        assert (by, value) == (By.TAG_NAME, 'h1')\n"
        "        return FakeElement()\n\n"
        "@pytest.fixture\n"
        "def driver():\n"
        "    return FakeDriver()\n",
        encoding="utf-8",
    )

    junit_path = tmp_path / "junit.xml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(junit_path),
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    result = parse_junit_xml(junit_path)
    assert (result.total, result.passed, result.failed, result.errors) == (1, 1, 0, 0)


def test_locator_failure_diagnosis_produces_review_only_proposal(tmp_path: Path):
    dom_path = tmp_path / "dom.html"
    dom_path.write_text(
        "<button data-testid='submit-login'>Sign in</button>",
        encoding="utf-8",
    )
    report = FailureReport(
        exception_type="NoSuchElementException",
        message="No such element: #old-submit",
        locator_strategy="css",
        locator_value="#old-submit",
        dom_snapshot=str(dom_path),
    )
    analysis = FailureAnalyzer().analyze(report)
    assert analysis.category is FailureCategory.LOCATOR_DRIFT

    source_path = tmp_path / "test_login.py"
    original_source = "submit_button = '#old-submit'\n"
    source_path.write_text(original_source, encoding="utf-8")
    provider = FakeProvider(
        json.dumps(
            {
                "new_locator": "[data-testid='submit-login']",
                "strategy": "css",
                "rationale": "The captured DOM identifies the submit button by its test ID.",
                "confidence": 0.9,
                "risks": [],
            }
        )
    )

    proposal = propose_locator_healing(report, source_path, provider)

    assert proposal.new_locator == "[data-testid='submit-login']"
    assert proposal.human_review_required is True
    assert proposal.applied is False
    assert proposal.validation == "not_run"
    assert source_path.read_text(encoding="utf-8") == original_source
    assert "submit-login" in proposal.proposed_diff


def test_selenium_wrapper_against_local_page(tmp_path: Path):
    page_path = tmp_path / "page.html"
    page_path.write_text(
        "<!doctype html><html><body>"
        '<label for="email">Email</label><input id="email">'
        '<button type="button" onclick="document.querySelector(\'#status\').textContent=\'Saved\'">'
        "Continue</button><p id=\"status\">Ready</p>"
        "</body></html>",
        encoding="utf-8",
    )
    agent = Autopilot(config=AutopilotConfig(timeout=5))
    try:
        agent.start()
    except WebDriverException as exc:
        if os.environ.get("AUTOPILOT_REQUIRE_BROWSER") == "1":
            raise
        pytest.skip(f"Chrome is unavailable for the local browser integration test: {exc}")

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        agent.open(f"http://127.0.0.1:{server.server_port}/page.html")
        agent.get_by_label("Email").fill("test@example.test")
        agent.get_by_role("button", "Continue").click()
        agent.expect_text_contains(agent.locator("#status"), "Saved")
    finally:
        agent.close()
        server.shutdown()
        server.server_close()
        server_thread.join()
