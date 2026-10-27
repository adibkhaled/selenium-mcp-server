from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.webdriver.common.by import By

from autopilot import (
    Autopilot,
    AutopilotConfig,
    AutopilotTimeoutError,
    capture_diagnostics,
)
from autopilot.assertions import expect_text_contains
from autopilot.locators import get_by_label, get_by_role, get_by_test_id


def test_role_label_test_id_and_selector_locator_strategies():
    driver = Mock()

    role_locator = get_by_role(driver, "button", "Sign in")
    label_locator = get_by_label(driver, "Email")
    test_id_locator = get_by_test_id(driver, "save-button")
    css_locator = Autopilot(driver).locator("main button")
    xpath_locator = Autopilot(driver).get_by_xpath("//main/button")

    assert role_locator.by == By.XPATH
    assert "self::button" in role_locator.value
    assert "Sign in" in role_locator.value
    assert label_locator.by == By.XPATH
    assert "Email" in label_locator.value
    assert test_id_locator.value == "//*[@data-testid='save-button']"
    assert css_locator.by == By.CSS_SELECTOR
    assert css_locator.value == "main button"
    assert xpath_locator.by == By.XPATH
    assert xpath_locator.value == "//main/button"


def test_ambiguous_locators_fail_instead_of_using_first_match():
    driver = Mock()
    driver.find_elements.return_value = [Mock(), Mock()]
    locator = Autopilot(driver).get_by_role("button", "Continue")

    with pytest.raises(ValueError, match="matched 2 elements"):
        locator.is_visible()


def test_fill_click_and_retrying_assertions():
    element = Mock()
    element.is_displayed.return_value = True
    element.is_enabled.return_value = True
    element.text = "Welcome to the dashboard"
    driver = Mock()
    driver.find_elements.return_value = [element]
    driver.current_url = "https://example.test/dashboard"
    browser = Autopilot(driver, AutopilotConfig(timeout=0.5))

    email = browser.get_by_label("Email")
    email.fill("test@example.test")
    browser.get_by_role("button", "Sign in").click()
    browser.expect_url_contains("/dashboard")
    browser.expect_text_contains(browser.locator("#welcome"), "dashboard")

    element.clear.assert_called_once_with()
    element.send_keys.assert_called_once_with("test@example.test")
    element.click.assert_called_once_with()


def test_timeout_includes_condition_and_current_url():
    driver = Mock()
    driver.current_url = "https://example.test/login"
    browser = Autopilot(driver, AutopilotConfig(timeout=0.01))

    with pytest.raises(AutopilotTimeoutError, match="current URL: https://example.test/login"):
        browser.expect_url_contains("/dashboard")


def test_open_resolves_relative_urls_and_rejects_unsupported_schemes():
    driver = Mock()
    browser = Autopilot(
        driver,
        AutopilotConfig(base_url="https://example.test", timeout=1),
    )

    browser.open("/login")
    driver.get.assert_called_once_with("https://example.test/login")

    with pytest.raises(ValueError, match="HTTP"):
        browser.open("javascript:alert(1)")


def test_browser_lifecycle_closes_driver(monkeypatch):
    driver = Mock()
    create_driver = Mock(return_value=driver)
    monkeypatch.setattr("autopilot.browser.webdriver.Chrome", create_driver)

    with Autopilot(config=AutopilotConfig(headless=True)) as browser:
        assert browser.driver is driver

    create_driver.assert_called_once()
    driver.quit.assert_called_once_with()


def test_diagnostics_write_screenshot_dom_and_metadata(tmp_path: Path):
    driver = Mock()
    driver.save_screenshot.side_effect = lambda path: Path(path).write_bytes(b"png") > 0
    driver.page_source = "<html><title>Failure</title></html>"
    driver.capabilities = {"browserName": "chrome", "browserVersion": "123"}
    driver.current_url = "https://example.test/failed"
    driver.title = "Failure"

    report = capture_diagnostics(driver, tmp_path, failed_action="click submit")

    assert report.errors == ()
    assert report.screenshot and Path(report.screenshot).read_bytes() == b"png"
    assert report.dom_snapshot
    assert Path(report.dom_snapshot).read_text(encoding="utf-8") == driver.page_source
    assert report.metadata
    metadata = json.loads(Path(report.metadata).read_text(encoding="utf-8"))
    assert metadata["browser"] == "chrome"
    assert metadata["url"] == driver.current_url
    assert metadata["failed_action"] == "click submit"


def test_config_and_selector_inputs_are_validated():
    with pytest.raises(ValueError, match="finite number greater than zero"):
        AutopilotConfig(timeout=0)

    with pytest.raises(ValueError, match="CSS selectors and XPath"):
        Autopilot(Mock()).locator("button", by=By.ID)

    with pytest.raises(ValueError, match="attribute name"):
        get_by_test_id(Mock(), "save", "bad attribute")


def test_text_assertion_times_out_when_text_is_not_present():
    element = Mock()
    element.is_displayed.return_value = True
    element.text = "Still loading"
    driver = Mock()
    driver.find_elements.return_value = [element]
    locator = Autopilot(driver, AutopilotConfig(timeout=0.01)).locator("#status")

    with pytest.raises(AutopilotTimeoutError, match="text 'Ready'"):
        expect_text_contains(locator, "Ready")
