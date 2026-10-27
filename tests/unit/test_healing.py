from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from autopilot.healing import (
    FailureAnalyzer,
    FailureCategory,
    FailureReport,
    HealingError,
    propose_locator_healing,
)


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def _report(**updates) -> FailureReport:
    values = {
        "exception_type": "NoSuchElementException",
        "message": "No such element: #old-submit",
        "traceback": "test_login.py:42",
        "browser": "chrome",
        "url": "https://test.example/login",
        "failed_action": "submit login",
        "test_file": "tests/test_login.py",
        "test_name": "test_valid_login",
        "locator_strategy": "css",
        "locator_value": "#old-submit",
    }
    values.update(updates)
    return FailureReport(**values)


def _proposal_response(**updates) -> str:
    value = {
        "new_locator": "[data-testid='submit-login']",
        "strategy": "css",
        "rationale": "The current DOM evidence identifies this stable test id on the submit button.",
        "confidence": 0.9,
        "risks": ["Confirm the test id is stable across supported builds."],
    }
    value.update(updates)
    return json.dumps(value)


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_report(), FailureCategory.LOCATOR_DRIFT),
        (
            _report(
                exception_type="TimeoutException",
                message="Timed out waiting for visibility",
                locator_strategy=None,
                locator_value=None,
            ),
            FailureCategory.SYNCHRONIZATION,
        ),
        (
            _report(
                exception_type="AssertionError",
                message="assert 'Home' == 'Dashboard'",
                assertion_failure=True,
                locator_strategy=None,
                locator_value=None,
            ),
            FailureCategory.APPLICATION_DEFECT,
        ),
        (
            _report(
                exception_type="ValueError",
                message="invalid test data",
                test_data_validated=False,
                locator_strategy=None,
                locator_value=None,
            ),
            FailureCategory.INVALID_TEST_DATA,
        ),
        (
            _report(
                exception_type="SessionNotCreatedException",
                message="Unable to obtain driver",
                browser_started=False,
                locator_strategy=None,
                locator_value=None,
            ),
            FailureCategory.ENVIRONMENT,
        ),
        (
            _report(
                exception_type="RuntimeError",
                message="unrecognized application failure",
                locator_strategy=None,
                locator_value=None,
            ),
            FailureCategory.UNKNOWN,
        ),
    ],
)
def test_failure_analyzer_classifies_report(report, expected):
    analysis = FailureAnalyzer().analyze(report)

    assert analysis.category == expected
    assert 0 <= analysis.confidence <= 1
    assert analysis.summary
    assert analysis.evidence
    assert analysis.next_steps


def test_failure_report_validates_shape_and_locator_pair():
    with pytest.raises(HealingError, match="non-empty 'exception_type'"):
        FailureReport.from_dict({"exception_type": "", "message": "failed"})

    with pytest.raises(HealingError, match="provided together"):
        FailureReport.from_dict(
            {
                "exception_type": "NoSuchElementException",
                "message": "missing",
                "locator_strategy": "css",
            }
        )

    with pytest.raises(HealingError, match="Unknown failure report fields"):
        FailureReport.from_dict(
            {"exception_type": "RuntimeError", "message": "failed", "secret": "value"}
        )


def test_locator_proposal_contains_minimal_diff_and_live_uniqueness(tmp_path: Path):
    source_path = tmp_path / "test_login.py"
    source = (
        "from selenium.webdriver.common.by import By\n"
        "def test_login(driver):\n"
        "    button = driver.find_element(By.CSS_SELECTOR, '#old-submit')\n"
        "    button.click()\n"
        "    assert driver.title == 'Dashboard'\n"
    )
    source_path.write_text(source, encoding="utf-8")
    dom_path = tmp_path / "current.html"
    dom_path.write_text(
        '<button data-testid="submit-login">Sign in</button>',
        encoding="utf-8",
    )
    report = _report(dom_snapshot=str(dom_path))
    provider = FakeProvider(_proposal_response())
    driver = Mock()
    driver.find_elements.return_value = [Mock()]

    proposal = propose_locator_healing(report, source_path, provider, driver=driver)

    assert proposal.uniqueness == "unique"
    assert proposal.locator_match_count == 1
    assert proposal.confidence == 0.9
    assert proposal.human_review_required is True
    assert proposal.applied is False
    assert proposal.validation == "not_run"
    assert "-    button = driver.find_element(By.CSS_SELECTOR, '#old-submit')" in proposal.proposed_diff
    assert "+    button = driver.find_element(By.CSS_SELECTOR, \"[data-testid='submit-login']\")" in proposal.proposed_diff
    changed_lines = [
        line
        for line in proposal.proposed_diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert all("assert driver.title" not in line for line in changed_lines)
    assert "data-testid" in provider.calls[0][1]


def test_locator_proposal_caps_confidence_when_uniqueness_is_not_checked(tmp_path: Path):
    source = tmp_path / "test_login.py"
    source.write_text("locator = '#old-submit'\n", encoding="utf-8")

    proposal = propose_locator_healing(
        _report(),
        source,
        FakeProvider(_proposal_response(confidence=0.99)),
    )

    assert proposal.uniqueness == "not_checked"
    assert proposal.locator_match_count is None
    assert proposal.confidence == 0.5
    assert any("not checked" in risk for risk in proposal.risks)


def test_locator_proposal_rejects_non_unique_candidate_and_wrong_failure_class(tmp_path: Path):
    source = tmp_path / "test_login.py"
    source.write_text("locator = '#old-submit'\n", encoding="utf-8")
    driver = Mock()
    driver.find_elements.return_value = [Mock(), Mock()]

    with pytest.raises(HealingError, match="matched 2 elements"):
        propose_locator_healing(
            _report(),
            source,
            FakeProvider(_proposal_response()),
            driver=driver,
        )

    with pytest.raises(HealingError, match="not appropriate"):
        propose_locator_healing(
            _report(exception_type="AssertionError", message="assert false"),
            source,
            FakeProvider(_proposal_response()),
        )


def test_locator_proposal_requires_exactly_one_old_value_and_valid_candidate(tmp_path: Path):
    source = tmp_path / "test_login.py"
    source.write_text(
        "first = '#old-submit'\nsecond = '#old-submit'\n",
        encoding="utf-8",
    )
    with pytest.raises(HealingError, match="found 2 occurrences"):
        propose_locator_healing(
            _report(),
            source,
            FakeProvider(_proposal_response()),
        )

    source.write_text("locator = '#old-submit'\n", encoding="utf-8")
    with pytest.raises(HealingError, match="must be css, xpath"):
        propose_locator_healing(
            _report(),
            source,
            FakeProvider(_proposal_response(strategy="javascript")),
        )


def test_proposal_provider_cannot_supply_a_custom_patch_or_change_assertions(tmp_path: Path):
    source = tmp_path / "test_login.py"
    source.write_text(
        "locator = '#old-submit'\nassert expected_result == 'Dashboard'\n",
        encoding="utf-8",
    )
    response = _proposal_response()
    candidate = json.loads(response)
    candidate["proposed_diff"] = "delete the assertion"

    with pytest.raises(HealingError, match="Unknown healing field"):
        propose_locator_healing(
            _report(),
            source,
            FakeProvider(json.dumps(candidate)),
        )

    assert "assert expected_result == 'Dashboard'" in source.read_text(encoding="utf-8")
