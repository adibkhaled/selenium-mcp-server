from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC

from .locators import Locator
from .waits import wait_until


def expect_url_contains(
    driver: WebDriver,
    expected: str,
    timeout: float = 10.0,
) -> None:
    if not expected:
        raise ValueError("expected URL fragment must not be empty.")
    wait_until(
        driver,
        EC.url_contains(expected),
        timeout=timeout,
        description=f"URL to contain {expected!r}",
    )


def expect_visible(locator: Locator, timeout: float | None = None) -> None:
    wait_until(
        locator.driver,
        lambda _driver: (
            element
            if (element := locator._find_unique()).is_displayed()
            else False
        ),
        timeout=timeout or locator.timeout,
        description=f"{locator.label} to be visible",
    )


def expect_text_contains(
    locator: Locator,
    expected: str,
    timeout: float | None = None,
) -> None:
    if not expected:
        raise ValueError("expected text must not be empty.")
    wait_until(
        locator.driver,
        lambda _driver: (
            element
            if (element := locator._find_unique()).is_displayed()
            and expected in element.text
            else False
        ),
        timeout=timeout or locator.timeout,
        description=f"text {expected!r} in {locator.label}",
    )
