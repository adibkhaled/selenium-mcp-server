from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from autopilot.generation import (
    GenerationError,
    TestGenerator as AutopilotTestGenerator,
    _parse_generated_files,
)
from autopilot.planning import (
    PlanningError,
    TestPlan as AutopilotTestPlan,
    TestPlanner as AutopilotTestPlanner,
)
from autopilot.provider import OpenAICompatibleProvider, ProviderError


PLAN_DATA = {
    "schema_version": "1.0",
    "summary": "Login behavior from stated acceptance criteria.",
    "scenarios": [
        {
            "id": "valid-login",
            "title": "User signs in with valid credentials",
            "priority": "high",
            "category": "positive",
            "preconditions": ["A test account exists."],
            "steps": ["Open the sign-in page.", "Submit valid test credentials."],
            "expected": ["The dashboard is displayed."],
        }
    ],
    "ambiguities": [],
    "risks": ["The test account must be isolated from production."],
}

GENERATED_RESPONSE = {
    "files": [
        {
            "path": "pages/login_page.py",
            "content": (
                "from selenium.webdriver.common.by import By\n"
                "from selenium.webdriver.support import expected_conditions as EC\n"
                "from selenium.webdriver.support.ui import WebDriverWait\n\n"
                "class LoginPage:\n"
                "    def __init__(self, driver):\n"
                "        self.driver = driver\n\n"
                "    def open(self):\n"
                "        self.driver.get('https://test.example/login')\n\n"
                "    def title(self):\n"
                "        return WebDriverWait(self.driver, 5).until(\n"
                "            EC.visibility_of_element_located((By.TAG_NAME, 'h1'))\n"
                "        ).text\n"
            ),
        },
        {
            "path": "tests/test_login.py",
            "content": (
                "from pages.login_page import LoginPage\n\n"
                "def test_login_page_has_heading(driver):\n"
                "    page = LoginPage(driver)\n"
                "    page.open()\n"
                "    assert page.title() == 'Sign in'\n"
            ),
        },
    ],
    "notes": ["Replace the example URL with an approved test environment."],
}


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def _plan() -> TestPlan:
    return AutopilotTestPlan.from_dict(PLAN_DATA)


def test_planner_builds_structured_plan_from_mock_provider():
    response = json.dumps(PLAN_DATA)
    provider = FakeProvider(response)

    plan = AutopilotTestPlanner(provider).create_plan(
        "A valid user reaches the dashboard after signing in.",
        {"src/auth.py": "def authenticate(user): ..."},
    )

    assert plan.scenarios[0].id == "valid-login"
    assert plan.to_dict() == PLAN_DATA
    assert "src/auth.py" in provider.calls[0][1]
    assert "Do not infer or invent" in provider.calls[0][1]


def test_planner_rejects_empty_requirements_invalid_json_and_invalid_plan():
    with pytest.raises(ValueError, match="must not be empty"):
        AutopilotTestPlanner(FakeProvider("{}")).create_plan(" ")

    with pytest.raises(PlanningError, match="invalid JSON"):
        AutopilotTestPlanner(FakeProvider("not-json")).create_plan("A stated requirement.")

    invalid_plan = dict(PLAN_DATA)
    invalid_plan["scenarios"] = []
    with pytest.raises(PlanningError, match="non-empty array"):
        AutopilotTestPlan.from_dict(invalid_plan)


def test_test_plan_validation_rejects_unknown_fields_duplicate_ids_and_missing_expected():
    unknown = {**PLAN_DATA, "unexpected": True}
    with pytest.raises(PlanningError, match="Unknown test plan field"):
        AutopilotTestPlan.from_dict(unknown)

    duplicate = json.loads(json.dumps(PLAN_DATA))
    duplicate["scenarios"].append(duplicate["scenarios"][0])
    with pytest.raises(PlanningError, match="Duplicate scenario id"):
        AutopilotTestPlan.from_dict(duplicate)

    missing_expected = json.loads(json.dumps(PLAN_DATA))
    del missing_expected["scenarios"][0]["expected"]
    with pytest.raises(PlanningError, match="expected is required"):
        AutopilotTestPlan.from_dict(missing_expected)


def test_generator_creates_page_objects_tests_and_project_setup(tmp_path: Path):
    provider = FakeProvider(json.dumps(GENERATED_RESPONSE))
    output = tmp_path / "generated_tests"

    result = AutopilotTestGenerator(provider).generate(_plan(), output)

    assert result.output_dir == output.resolve()
    assert len(result.files) == 6
    assert (output / "pages" / "login_page.py").is_file()
    assert (output / "tests" / "test_login.py").is_file()
    assert (output / "tests" / "conftest.py").is_file()
    assert (output / "pyproject.toml").is_file()
    assert "fixed sleeps" in provider.calls[0][0]
    assert result.notes == tuple(GENERATED_RESPONSE["notes"])


def test_generator_refuses_overwrite_unless_explicitly_requested(tmp_path: Path):
    output = tmp_path / "generated_tests"
    generator = AutopilotTestGenerator(FakeProvider(json.dumps(GENERATED_RESPONSE)))
    generator.generate(_plan(), output)
    original = (output / "tests" / "test_login.py").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        generator.generate(_plan(), output)

    replacement = json.loads(json.dumps(GENERATED_RESPONSE))
    replacement["files"][1]["content"] = "def test_updated(driver):\n    assert driver\n"
    result = AutopilotTestGenerator(FakeProvider(json.dumps(replacement))).generate(
        _plan(),
        output,
        overwrite=True,
    )
    assert (output / "tests" / "test_login.py").read_text(encoding="utf-8") != original
    assert result.output_dir == output.resolve()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "tests/../../outside.py",
        "C:/outside.py",
        "tests\\test_bad.py",
        "README.md",
        "tests/conftest.py",
        "src/test_bad.py",
    ],
)
def test_generator_rejects_unsafe_or_unapproved_model_paths(path: str):
    payload = {
        "files": [{"path": path, "content": "def test_sample():\n    assert True\n"}],
        "notes": [],
    }

    with pytest.raises(GenerationError, match="path must be"):
        _parse_generated_files(json.dumps(payload))


@pytest.mark.parametrize(
    "content",
    [
        "import os\n\ndef test_bad():\n    os.system('whoami')\n",
        "def test_bad():\n    eval('1 + 1')\n",
        "def test_bad():\n    getattr(__builtins__, 'eval')('1 + 1')\n",
        "import time\n\ndef test_bad():\n    time.sleep(2)\n",
        "driver = webdriver.Chrome()\n",
        "def test_bad(:\n    pass\n",
    ],
)
def test_generator_rejects_unsafe_or_invalid_python(content: str):
    payload = {
        "files": [
            {"path": "pages/sample_page.py", "content": "class SamplePage:\n    pass\n"},
            {"path": "tests/test_sample.py", "content": content},
        ],
        "notes": [],
    }

    with pytest.raises(GenerationError):
        _parse_generated_files(json.dumps(payload))


def test_generator_rejects_missing_page_objects_or_tests(tmp_path: Path):
    no_page = {
        "files": [{"path": "tests/test_sample.py", "content": "def test_sample():\n    assert True\n"}],
        "notes": [],
    }
    with pytest.raises(GenerationError, match="at least one Page Object"):
        AutopilotTestGenerator(FakeProvider(json.dumps(no_page))).generate(
            _plan(),
            tmp_path / "no-page",
        )


def test_provider_requires_secure_remote_endpoint_and_model():
    with pytest.raises(ValueError, match="must use HTTPS"):
        OpenAICompatibleProvider("http://api.example.test/v1", "model")
    with pytest.raises(ValueError, match="must not be empty"):
        OpenAICompatibleProvider("http://localhost:11434/v1", " ")


def test_openai_compatible_provider_supports_local_endpoint_without_api_key(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": '{"ok": true}'}}]}
    ).encode()
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr("autopilot.provider.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        "http://localhost:11434/v1",
        "local-model",
        timeout=4,
    )

    assert provider.generate_json("system", "user") == '{"ok": true}'
    assert captured["request"].full_url == (
        "http://localhost:11434/v1/chat/completions"
    )
    assert captured["request"].get_header("Authorization") is None
    assert captured["timeout"] == 4


def test_openai_compatible_provider_reports_malformed_response(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"not-json"
    monkeypatch.setattr("autopilot.provider.urlopen", lambda *_args, **_kwargs: response)
    provider = OpenAICompatibleProvider("http://localhost:11434/v1", "local-model")

    with pytest.raises(ProviderError, match="malformed response JSON"):
        provider.generate_json("system", "user")
