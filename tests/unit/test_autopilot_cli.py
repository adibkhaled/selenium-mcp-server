from __future__ import annotations

import json
from pathlib import Path

from autopilot import cli


PLAN_RESPONSE = json.dumps(
    {
        "schema_version": "1.0",
        "summary": "A verified basic flow.",
        "scenarios": [
            {
                "id": "home-page",
                "title": "Open the home page",
                "priority": "medium",
                "category": "positive",
                "preconditions": [],
                "steps": ["Open the approved test home page."],
                "expected": ["The home page heading is visible."],
            }
        ],
        "ambiguities": [],
        "risks": [],
    }
)

GENERATION_RESPONSE = json.dumps(
    {
        "files": [
            {
                "path": "pages/home_page.py",
                "content": (
                    "from selenium.webdriver.common.by import By\n\n"
                    "class HomePage:\n"
                    "    def __init__(self, driver):\n"
                    "        self.driver = driver\n"
                ),
            },
            {
                "path": "tests/test_home_page.py",
                "content": (
                    "from pages.home_page import HomePage\n\n"
                    "def test_home_page(driver):\n"
                    "    page = HomePage(driver)\n"
                    "    assert page.driver is driver\n"
                ),
            },
        ],
        "notes": [],
    }
)


class SequenceProvider:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)

    def generate_json(self, _system_prompt: str, _user_prompt: str) -> str:
        return next(self.responses)


def test_cli_plan_then_generate_project_with_mocked_provider(tmp_path: Path, monkeypatch, capsys):
    requirements = tmp_path / "requirements.md"
    requirements.write_text(
        "Opening the home page displays its heading.",
        encoding="utf-8",
    )
    plan_path = tmp_path / "artifacts" / "test-plan.json"
    provider = SequenceProvider([PLAN_RESPONSE, GENERATION_RESPONSE])
    monkeypatch.setattr(cli, "provider_from_environment", lambda: provider)

    assert cli.main(
        ["plan", "--requirements", str(requirements), "--output", str(plan_path)]
    ) == 0
    plan_output = json.loads(capsys.readouterr().out)
    assert plan_output["scenario_count"] == 1
    assert json.loads(plan_path.read_text(encoding="utf-8"))["summary"] == "A verified basic flow."

    output_dir = tmp_path / "generated_tests"
    assert cli.main(
        ["generate", "--plan", str(plan_path), "--output", str(output_dir)]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["review_required"] is True
    assert (output_dir / "tests" / "test_home_page.py").is_file()


def test_cli_does_not_replace_existing_plan_without_flag(tmp_path: Path, monkeypatch, capsys):
    requirements = tmp_path / "requirements.md"
    requirements.write_text("A specific stated requirement.", encoding="utf-8")
    output = tmp_path / "test-plan.json"
    output.write_text("keep existing", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "provider_from_environment",
        lambda: SequenceProvider([PLAN_RESPONSE]),
    )

    exit_code = cli.main(
        ["plan", "--requirements", str(requirements), "--output", str(output)]
    )

    assert exit_code == 2
    assert output.read_text(encoding="utf-8") == "keep existing"
    assert "Pass --overwrite" in capsys.readouterr().err


def test_cli_analyze_is_deterministic_and_does_not_initialize_provider(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    failure_report = tmp_path / "failure.json"
    failure_report.write_text(
        json.dumps(
            {
                "exception_type": "NoSuchElementException",
                "message": "no such element: #submit",
                "locator_strategy": "css",
                "locator_value": "#submit",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "provider_from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("analysis must not use a provider")),
    )
    output = tmp_path / "analysis.json"

    assert cli.main(["analyze", "--report", str(failure_report), "--output", str(output)]) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["category"] == "locator_drift"
    assert result["confidence"] > 0
    assert "locator_drift" in capsys.readouterr().out.lower()


def test_cli_heal_writes_review_only_proposal_with_mocked_provider(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    report_path = tmp_path / "failure.json"
    report_path.write_text(
        json.dumps(
            {
                "exception_type": "NoSuchElementException",
                "message": "no such element: #submit",
                "test_file": "tests/test_login.py",
                "locator_strategy": "css",
                "locator_value": "#submit",
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "test_login.py"
    source_path.write_text("locator = '#submit'\n", encoding="utf-8")
    provider = SequenceProvider(
        [
            json.dumps(
                {
                    "new_locator": "[data-testid='submit-login']",
                    "strategy": "css",
                    "rationale": "The captured DOM shows the stable test id.",
                    "confidence": 0.8,
                    "risks": [],
                }
            )
        ]
    )
    monkeypatch.setattr(cli, "provider_from_environment", lambda: provider)
    output_path = tmp_path / "proposal.json"

    assert cli.main(
        [
            "heal",
            "--report",
            str(report_path),
            "--source",
            str(source_path),
            "--output",
            str(output_path),
        ]
    ) == 0

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["human_review_required"] is True
    assert result["applied"] is False
    assert result["uniqueness"] == "not_checked"
    assert json.loads(capsys.readouterr().out)["applied"] is False


def test_cli_report_converts_junit_and_marks_missing_report_unavailable(
    tmp_path: Path,
    capsys,
):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite tests="1"><testcase classname="test_home" name="test_title"/></testsuite>',
        encoding="utf-8",
    )
    output = tmp_path / "test-results.json"

    assert cli.main(["report", "--junit", str(junit), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["source"] == "junit"
    assert result["summary"]["passed"] == 1
    capsys.readouterr()

    missing_output = tmp_path / "unavailable.json"
    missing_junit = tmp_path / "missing.xml"
    assert cli.main(
        [
            "report",
            "--junit",
            str(missing_junit),
            "--output",
            str(missing_output),
        ]
    ) == 0
    unavailable = json.loads(missing_output.read_text(encoding="utf-8"))
    assert unavailable["source"] == "unavailable"
    assert json.loads(capsys.readouterr().out)["source"] == "unavailable"
