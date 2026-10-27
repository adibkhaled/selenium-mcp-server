from __future__ import annotations

from dataclasses import dataclass
import re

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.webdriver import WebDriver

from .waits import wait_until


_ROLE_TAGS = {
    "button": "self::button or self::input[@type='button' or @type='submit' or @type='reset']",
    "checkbox": "self::input[@type='checkbox']",
    "link": "self::a[@href]",
    "radio": "self::input[@type='radio']",
    "textbox": (
        "self::textarea or self::input[not(@type) or @type='text' or "
        "@type='email' or @type='password' or @type='tel' or @type='url']"
    ),
    "searchbox": "self::input[@type='search']",
    "combobox": "self::select or self::input[@role='combobox']",
    "option": "self::option",
    "tab": "self::button[@role='tab']",
}


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


def role_xpath(role: str, name: str) -> str:
    normalized_role = role.strip().lower()
    if not normalized_role:
        raise ValueError("role must not be empty.")
    role_literal = _xpath_literal(normalized_role)
    name_literal = _xpath_literal(name)
    native_role = _ROLE_TAGS.get(normalized_role, "false()")
    role_match = f"@role={role_literal} or {native_role}"
    name_match = " or ".join(
        (
            f"normalize-space(string(.))={name_literal}",
            f"@aria-label={name_literal}",
            f"@title={name_literal}",
            f"@value={name_literal}",
            f"@placeholder={name_literal}",
            f"@id=//label[normalize-space(string(.))={name_literal}]/@for",
            f"ancestor::label[normalize-space(string(.))={name_literal}]",
        )
    )
    return f"//*[{role_match}][{name_match}]"


def label_xpath(label: str) -> str:
    literal = _xpath_literal(label)
    return (
        "//*[self::input or self::textarea or self::select]"
        f"[@id=//label[normalize-space(string(.))={literal}]/@for "
        f"or ancestor::label[normalize-space(string(.))={literal}]]"
    )


@dataclass(frozen=True)
class Locator:
    driver: WebDriver
    by: str
    value: str
    timeout: float = 10.0
    description: str | None = None

    @property
    def label(self) -> str:
        return self.description or f"{self.by}={self.value!r}"

    def _find_unique(self, _driver: WebDriver | None = None) -> WebElement:
        elements = self.driver.find_elements(self.by, self.value)
        if not elements:
            raise NoSuchElementException(f"No element found for {self.label}")
        if len(elements) > 1:
            raise ValueError(f"Locator {self.label} matched {len(elements)} elements; expected one.")
        return elements[0]

    def wait_for_visible(self) -> WebElement:
        return wait_until(
            self.driver,
            lambda _driver: (
                element
                if (element := self._find_unique()).is_displayed()
                else False
            ),
            timeout=self.timeout,
            description=f"{self.label} to be visible",
        )

    def click(self) -> None:
        element = wait_until(
            self.driver,
            lambda _driver: (
                element
                if (element := self._find_unique()).is_displayed() and element.is_enabled()
                else False
            ),
            timeout=self.timeout,
            description=f"{self.label} to be clickable",
        )
        element.click()

    def fill(self, value: str) -> None:
        element = self.wait_for_visible()
        if not element.is_enabled():
            raise ValueError(f"Cannot fill disabled element: {self.label}")
        element.clear()
        element.send_keys(value)

    def text_content(self) -> str:
        return self.wait_for_visible().text

    def is_visible(self) -> bool:
        try:
            return self._find_unique().is_displayed()
        except NoSuchElementException:
            return False


def get_by_role(
    driver: WebDriver,
    role: str,
    name: str,
    timeout: float = 10.0,
) -> Locator:
    return Locator(
        driver,
        By.XPATH,
        role_xpath(role, name),
        timeout,
        f"role {role!r} with accessible name {name!r}",
    )


def get_by_label(driver: WebDriver, label: str, timeout: float = 10.0) -> Locator:
    return Locator(
        driver,
        By.XPATH,
        label_xpath(label),
        timeout,
        f"label {label!r}",
    )


def get_by_test_id(
    driver: WebDriver,
    test_id: str,
    attribute: str = "data-testid",
    timeout: float = 10.0,
) -> Locator:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", attribute):
        raise ValueError("test-id attribute must be a valid HTML attribute name.")
    return Locator(
        driver,
        By.XPATH,
        f"//*[@{attribute}={_xpath_literal(test_id)}]",
        timeout,
        f"test id {test_id!r}",
    )
