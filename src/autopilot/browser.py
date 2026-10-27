from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .assertions import expect_text_contains, expect_url_contains, expect_visible
from .locators import Locator, get_by_label, get_by_role, get_by_test_id


@dataclass(frozen=True)
class AutopilotConfig:
    browser: str = "chrome"
    headless: bool = True
    timeout: float = 10.0
    base_url: str | None = None
    window_size: tuple[int, int] = (1440, 1000)

    def __post_init__(self) -> None:
        if self.browser != "chrome":
            raise ValueError("Phase 1 currently supports Chrome only.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite number greater than zero.")
        if len(self.window_size) != 2 or any(size <= 0 for size in self.window_size):
            raise ValueError("window_size must contain two positive dimensions.")


class Autopilot:
    def __init__(
        self,
        driver: WebDriver | None = None,
        config: AutopilotConfig | None = None,
    ) -> None:
        self.config = config or AutopilotConfig()
        self._driver = driver

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            self.start()
        return self._driver

    def start(self) -> "Autopilot":
        if self._driver is not None:
            return self
        options = Options()
        if self.config.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(
            f"--window-size={self.config.window_size[0]},{self.config.window_size[1]}"
        )
        self._driver = webdriver.Chrome(options=options, service=Service())
        return self

    def close(self) -> None:
        driver, self._driver = self._driver, None
        if driver is not None:
            driver.quit()

    def __enter__(self) -> "Autopilot":
        return self.start()

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def open(self, url: str) -> None:
        if not url.strip():
            raise ValueError("URL must not be empty.")
        target = urljoin(self.config.base_url, url) if self.config.base_url else url
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must be absolute HTTP(S), or relative to a configured base_url.")
        self.driver.get(target)

    def get_by_role(self, role: str, name: str) -> Locator:
        return get_by_role(self.driver, role, name, self.config.timeout)

    def get_by_label(self, label: str) -> Locator:
        return get_by_label(self.driver, label, self.config.timeout)

    def get_by_test_id(
        self,
        test_id: str,
        attribute: str = "data-testid",
    ) -> Locator:
        return get_by_test_id(
            self.driver,
            test_id,
            attribute,
            self.config.timeout,
        )

    def locator(self, selector: str, by: str = By.CSS_SELECTOR) -> Locator:
        if by not in {By.CSS_SELECTOR, By.XPATH}:
            raise ValueError("locator supports CSS selectors and XPath only.")
        if not selector.strip():
            raise ValueError("selector must not be empty.")
        return Locator(self.driver, by, selector, self.config.timeout)

    def get_by_xpath(self, expression: str) -> Locator:
        return self.locator(expression, By.XPATH)

    def expect_url_contains(self, expected: str, timeout: float | None = None) -> None:
        expect_url_contains(
            self.driver,
            expected,
            self.config.timeout if timeout is None else timeout,
        )

    def expect_visible(self, locator: Locator, timeout: float | None = None) -> None:
        expect_visible(locator, self.config.timeout if timeout is None else timeout)

    def expect_text_contains(
        self,
        locator: Locator,
        expected: str,
        timeout: float | None = None,
    ) -> None:
        expect_text_contains(
            locator,
            expected,
            self.config.timeout if timeout is None else timeout,
        )
