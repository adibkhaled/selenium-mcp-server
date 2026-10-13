from __future__ import annotations

import math
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.select import Select


MAX_WAIT_SECONDS = 30
_CLICK_ROLES = {
    "button",
    "checkbox",
    "link",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "switch",
    "tab",
}
_TYPE_ROLES = {"combobox", "searchbox", "spinbutton", "textbox"}
_STATE_PROPERTIES = {
    "checked",
    "disabled",
    "editable",
    "expanded",
    "focusable",
    "invalid",
    "level",
    "modal",
    "multiselectable",
    "pressed",
    "readonly",
    "required",
    "selected",
    "setsize",
    "posinset",
}


class BrowserAutomationError(Exception):
    """An expected, user-actionable browser automation failure."""


class StaleReferenceError(BrowserAutomationError):
    """A reference does not identify an actionable element in the current page."""


@dataclass(frozen=True)
class BrowserSettings:
    browser: str = "chrome"
    headless: bool = True
    binary: str | None = None


@dataclass(frozen=True)
class ElementReference:
    reference: str
    backend_node_id: int
    role: str
    tag_name: str
    actions: tuple[str, ...]


class ReferenceIndex:
    def __init__(self) -> None:
        self._next_id = 1
        self._by_backend_id: dict[int, ElementReference] = {}
        self._by_reference: dict[str, ElementReference] = {}

    def reconcile(self, elements: list[ElementReference]) -> dict[int, ElementReference]:
        current_by_backend_id: dict[int, ElementReference] = {}
        current_by_reference: dict[str, ElementReference] = {}

        for element in elements:
            previous = self._by_backend_id.get(element.backend_node_id)
            reference = previous.reference if previous else f"e{self._next_id}"
            if previous is None:
                self._next_id += 1
            current = ElementReference(
                reference=reference,
                backend_node_id=element.backend_node_id,
                role=element.role,
                tag_name=element.tag_name,
                actions=element.actions,
            )
            current_by_backend_id[element.backend_node_id] = current
            current_by_reference[reference] = current

        self._by_backend_id = current_by_backend_id
        self._by_reference = current_by_reference
        return current_by_backend_id

    def get(self, reference: str) -> ElementReference:
        element = self._by_reference.get(reference)
        if element is None:
            raise StaleReferenceError(f"Unknown or stale element reference: {reference}")
        return element

    def invalidate(self) -> None:
        self._by_backend_id.clear()
        self._by_reference.clear()


def _ax_value(node: dict[str, Any], key: str) -> Any:
    value = node.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _ax_properties(node: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for property_value in node.get("properties", []):
        name = property_value.get("name")
        if name not in _STATE_PROPERTIES:
            continue
        value = property_value.get("value", {})
        if isinstance(value, dict):
            value = value.get("value")
        result[name] = value
    return result


def _element_actions(role: str, tag_name: str, properties: dict[str, Any]) -> tuple[str, ...]:
    role = role.lower()
    tag_name = tag_name.upper()
    actions: list[str] = []

    if role in _CLICK_ROLES or tag_name in {"A", "BUTTON", "INPUT", "OPTION", "SELECT", "SUMMARY"}:
        actions.append("click")
    editable = properties.get("editable")
    if (
        role in _TYPE_ROLES
        or tag_name == "TEXTAREA"
        or (tag_name == "INPUT" and role in _TYPE_ROLES)
        or (editable is not None and editable is not False and editable != "false")
    ):
        if tag_name != "INPUT" or role in _TYPE_ROLES:
            actions.append("type")
    if tag_name == "SELECT":
        actions.append("select")
    if role == "slider":
        actions.append("press_key")
    if actions:
        if "press_key" not in actions:
            actions.append("press_key")
    return tuple(actions)


class BrowserSession:
    def __init__(self, settings: BrowserSettings | None = None) -> None:
        self.settings = settings or BrowserSettings()
        self._driver: webdriver.Chrome | None = None
        self._references = ReferenceIndex()
        self._tab_ids: dict[str, str] = {}
        self._next_tab_id = 1
        self._window_property = f"__selenium_mcp_{uuid.uuid4().hex}"
        self._document_token = uuid.uuid4().hex

    @property
    def driver(self) -> webdriver.Chrome:
        if self._driver is None:
            options = Options()
            if self.settings.headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-dev-shm-usage")
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                options.add_argument("--no-sandbox")

            binary = self.settings.binary
            if self.settings.browser == "chromium" and binary is None:
                binary = shutil.which("chromium") or shutil.which("chromium-browser")
                if binary is None:
                    raise BrowserAutomationError(
                        "Chromium was selected but no chromium executable was found; "
                        "pass --browser-binary with its path."
                    )
            if binary:
                if not Path(binary).is_file():
                    raise BrowserAutomationError(f"Browser executable does not exist: {binary}")
                options.binary_location = binary

            try:
                self._driver = webdriver.Chrome(
                    options=options,
                    service=Service(log_output=sys.stderr),
                )
            except WebDriverException as exc:
                raise BrowserAutomationError(f"Could not start Chrome/Chromium: {exc}") from exc
        return self._driver

    def close(self) -> None:
        driver, self._driver = self._driver, None
        try:
            if driver is not None:
                driver.quit()
        finally:
            self._references.invalidate()
            self._tab_ids.clear()

    def _invalidate_document_references(self) -> None:
        self._references.invalidate()
        self._document_token = uuid.uuid4().hex

    def _sync_document(self) -> None:
        try:
            token = self.driver.execute_script(
                "return window[arguments[0]] || null",
                self._window_property,
            )
            if token != self._document_token:
                self._references.invalidate()
                self.driver.execute_script(
                    "window[arguments[0]] = arguments[1]; window[arguments[0] + '_elements'] "
                    "= Object.create(null)",
                    self._window_property,
                    self._document_token,
                )
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not inspect the current browser document: {exc}") from exc

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must be an absolute HTTP or HTTPS URL.")

    def navigate(self, url: str) -> dict[str, str]:
        self._validate_url(url)
        self._invalidate_document_references()
        try:
            self.driver.get(url)
            self._sync_document()
            return {"url": self.driver.current_url, "title": self.driver.title}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Navigation failed for {url}: {exc}") from exc

    def snapshot(self) -> dict[str, Any]:
        driver = self.driver
        self._sync_document()
        try:
            ax_tree = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})
            raw_nodes = ax_tree.get("nodes", [])
            nodes_by_id = {node.get("nodeId"): node for node in raw_nodes}
            candidate_elements: list[ElementReference] = []
            node_details: dict[str, tuple[str, str, dict[str, Any], int | None]] = {}
            seen_backend_ids: set[int] = set()

            for node in raw_nodes:
                node_id = node.get("nodeId")
                if node.get("ignored") or not node_id:
                    continue
                role = str(_ax_value(node, "role") or "generic")
                properties = _ax_properties(node)
                backend_id = node.get("backendDOMNodeId")
                tag_name = ""
                actions: tuple[str, ...] = ()

                if (
                    isinstance(backend_id, int)
                    and backend_id not in seen_backend_ids
                    and (
                        role.lower() in _CLICK_ROLES | _TYPE_ROLES | {"slider"}
                        or properties.get("editable") not in (None, False, "false")
                    )
                ):
                    seen_backend_ids.add(backend_id)
                    try:
                        description = driver.execute_cdp_cmd(
                            "DOM.describeNode",
                            {"backendNodeId": backend_id},
                        )
                        tag_name = str(description.get("node", {}).get("nodeName", ""))
                    except WebDriverException:
                        tag_name = ""
                    actions = _element_actions(role, tag_name, properties)
                    if actions:
                        candidate_elements.append(
                            ElementReference(
                                reference="",
                                backend_node_id=backend_id,
                                role=role,
                                tag_name=tag_name,
                                actions=actions,
                            )
                        )
                node_details[node_id] = (role, tag_name, properties, backend_id)

            current_by_backend_id = self._references.reconcile(candidate_elements)
            driver.execute_script(
                "window[arguments[0] + '_elements'] = Object.create(null)",
                self._window_property,
            )

            refs_by_node_id: dict[str, str] = {}
            for node in raw_nodes:
                backend_id = node.get("backendDOMNodeId")
                if not isinstance(backend_id, int) or backend_id not in current_by_backend_id:
                    continue
                element = current_by_backend_id[backend_id]
                try:
                    resolved = driver.execute_cdp_cmd(
                        "DOM.resolveNode",
                        {"backendNodeId": backend_id},
                    )
                except WebDriverException:
                    continue
                object_id = resolved.get("object", {}).get("objectId")
                if not object_id:
                    continue
                try:
                    result = driver.execute_cdp_cmd(
                        "Runtime.callFunctionOn",
                        {
                            "objectId": object_id,
                            "functionDeclaration": (
                                "function(property, reference) { "
                                "if (!this.isConnected) return false; "
                                "const registry = window[property + '_elements']; "
                                "registry[reference] = this; return true; }"
                            ),
                            "arguments": [
                                {"value": self._window_property},
                                {"value": element.reference},
                            ],
                            "returnByValue": True,
                        },
                    )
                except WebDriverException:
                    continue
                if result.get("result", {}).get("value") is True:
                    refs_by_node_id[node.get("nodeId")] = element.reference

            roots: list[dict[str, Any]] = []
            attached: set[str] = set()

            def append_node(node_id: str, parent: dict[str, Any] | None) -> None:
                node = nodes_by_id.get(node_id)
                if node is None or node.get("ignored"):
                    if node is not None:
                        for child_id in node.get("childIds", []):
                            append_node(child_id, parent)
                    return
                details = node_details.get(node_id)
                if details is None:
                    return
                role, _tag_name, properties, _backend_id = details
                item: dict[str, Any] = {
                    "role": role,
                    "name": _ax_value(node, "name"),
                    "children": [],
                }
                description = _ax_value(node, "description")
                value = _ax_value(node, "value")
                if description:
                    item["description"] = description
                if value is not None:
                    item["value"] = value
                if properties:
                    item["states"] = properties
                reference = refs_by_node_id.get(node_id)
                if reference:
                    item["ref"] = reference
                    item["actions"] = list(current_by_backend_id[node["backendDOMNodeId"]].actions)
                if parent is None:
                    roots.append(item)
                else:
                    parent["children"].append(item)
                attached.add(node_id)
                for child_id in node.get("childIds", []):
                    append_node(child_id, item)

            for node in raw_nodes:
                node_id = node.get("nodeId")
                if not node_id or node.get("ignored") or node_id in attached:
                    continue
                parent_id = node.get("parentId")
                parent = nodes_by_id.get(parent_id)
                if not parent_id or parent is None or parent.get("ignored"):
                    append_node(node_id, None)

            return {
                "url": driver.current_url,
                "title": driver.title,
                "tree": roots,
            }
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not retrieve the accessibility tree: {exc}") from exc

    def _resolve_element(self, reference: str, action: str | None = None) -> Any:
        self._sync_document()
        element = self._references.get(reference)
        if action and action not in element.actions:
            raise BrowserAutomationError(
                f"Element {reference} (role: {element.role}) does not support {action}."
            )
        try:
            web_element = self.driver.execute_script(
                "return window[arguments[0] + '_elements']?.[arguments[1]] || null",
                self._window_property,
                reference,
            )
            if web_element is None or not web_element.is_displayed():
                raise StaleReferenceError(f"Element reference is stale or not actionable: {reference}")
            if not web_element.is_enabled():
                raise BrowserAutomationError(f"Element is disabled: {reference}")
            return web_element
        except StaleReferenceError:
            raise
        except WebDriverException as exc:
            raise StaleReferenceError(f"Element reference is stale: {reference}") from exc

    def click(self, reference: str) -> dict[str, str]:
        element = self._resolve_element(reference, "click")
        try:
            element.click()
            return {"clicked": reference}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not click {reference}: {exc}") from exc

    def type_text(self, reference: str, text: str) -> dict[str, str]:
        element = self._resolve_element(reference, "type")
        try:
            element.send_keys(text)
            return {"typed": reference}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not type into {reference}: {exc}") from exc

    def select_option(self, reference: str, value: str) -> dict[str, str]:
        element = self._resolve_element(reference, "select")
        try:
            Select(element).select_by_value(value)
            return {"selected": value, "ref": reference}
        except (NoSuchElementException, WebDriverException) as exc:
            raise BrowserAutomationError(f"Could not select value {value!r} on {reference}: {exc}") from exc

    def press_key(self, reference: str, key: str) -> dict[str, str]:
        element = self._resolve_element(reference, "press_key")
        selenium_key = getattr(Keys, key.upper(), None)
        if selenium_key is None:
            if len(key) != 1:
                raise ValueError("key must be a Selenium key name (for example ENTER) or one character.")
            selenium_key = key
        try:
            element.send_keys(selenium_key)
            return {"pressed": key, "ref": reference}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not send key {key!r} to {reference}: {exc}") from exc

    @staticmethod
    def wait(seconds: float) -> dict[str, float]:
        if not math.isfinite(seconds) or seconds < 0 or seconds > MAX_WAIT_SECONDS:
            raise ValueError(f"seconds must be between 0 and {MAX_WAIT_SECONDS}.")
        time.sleep(seconds)
        return {"waited": seconds}

    def _tab_id(self, handle: str) -> str:
        tab_id = self._tab_ids.get(handle)
        if tab_id is None:
            tab_id = f"t{self._next_tab_id}"
            self._next_tab_id += 1
            self._tab_ids[handle] = tab_id
        return tab_id

    def list_tabs(self) -> dict[str, Any]:
        driver = self.driver
        handles = driver.window_handles
        self._tab_ids = {handle: tab_id for handle, tab_id in self._tab_ids.items() if handle in handles}
        tabs: list[dict[str, str]] = []
        active_tab: str | None = None
        active_handle = driver.current_window_handle
        try:
            for handle in handles:
                driver.switch_to.window(handle)
                tab_id = self._tab_id(handle)
                tabs.append({"id": tab_id, "url": driver.current_url, "title": driver.title})
                if handle == active_handle:
                    active_tab = tab_id
            driver.switch_to.window(active_handle)
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not list browser tabs: {exc}") from exc
        return {"tabs": tabs, "active": active_tab}

    def open_tab(self, url: str | None = None) -> dict[str, str]:
        if url is not None:
            self._validate_url(url)
        driver = self.driver
        try:
            driver.switch_to.new_window("tab")
            self._invalidate_document_references()
            handle = driver.current_window_handle
            tab_id = self._tab_id(handle)
            if url is not None:
                driver.get(url)
                self._sync_document()
            return {"id": tab_id, "url": driver.current_url, "title": driver.title}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not open a browser tab: {exc}") from exc

    def switch_tab(self, tab_id: str) -> dict[str, str]:
        handle = next((handle for handle, candidate in self._tab_ids.items() if candidate == tab_id), None)
        if handle is None or handle not in self.driver.window_handles:
            raise ValueError(f"Unknown tab reference: {tab_id}")
        try:
            self.driver.switch_to.window(handle)
            self._invalidate_document_references()
            self._sync_document()
            return {"id": tab_id, "url": self.driver.current_url, "title": self.driver.title}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not switch to tab {tab_id}: {exc}") from exc

    def close_tab(self, tab_id: str) -> dict[str, str]:
        handle = next((handle for handle, candidate in self._tab_ids.items() if candidate == tab_id), None)
        if handle is None or handle not in self.driver.window_handles:
            raise ValueError(f"Unknown tab reference: {tab_id}")
        if len(self.driver.window_handles) == 1:
            raise BrowserAutomationError("Cannot close the last browser tab.")
        try:
            active_handle = self.driver.current_window_handle
            was_active = active_handle == handle
            self.driver.switch_to.window(handle)
            self.driver.close()
            self._tab_ids.pop(handle, None)
            remaining_handles = self.driver.window_handles
            if was_active or active_handle not in remaining_handles:
                self.driver.switch_to.window(remaining_handles[0])
                self._invalidate_document_references()
                self._sync_document()
            else:
                self.driver.switch_to.window(active_handle)
            return {"closed": tab_id}
        except WebDriverException as exc:
            raise BrowserAutomationError(f"Could not close tab {tab_id}: {exc}") from exc
