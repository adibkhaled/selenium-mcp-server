from __future__ import annotations

from collections.abc import Callable
import math
from typing import TypeVar

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait


T = TypeVar("T")


class AutopilotTimeoutError(TimeoutError):
    """A browser condition was not satisfied within its configured timeout."""


def wait_until(
    driver: WebDriver,
    condition: Callable[[WebDriver], T],
    *,
    timeout: float,
    description: str,
    poll_frequency: float = 0.2,
) -> T:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite number greater than zero.")
    if not math.isfinite(poll_frequency) or poll_frequency <= 0:
        raise ValueError("poll_frequency must be a finite number greater than zero.")
    try:
        return WebDriverWait(
            driver,
            timeout=timeout,
            poll_frequency=poll_frequency,
        ).until(condition)
    except TimeoutException as exc:
        current_url = getattr(driver, "current_url", "<unavailable>")
        raise AutopilotTimeoutError(
            f"Timed out after {timeout:g}s waiting for {description}; "
            f"current URL: {current_url}"
        ) from exc
