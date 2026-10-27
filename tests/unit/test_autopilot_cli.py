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
