import math
from unittest.mock import Mock

import pytest
from selenium.webdriver.chrome.options import Options

from selenium_mcp_server.browser import (
    BrowserAutomationError,
    BrowserSession,
    BrowserSettings,
    ElementReference,
    MAX_WAIT_SECONDS,
    ReferenceIndex,
    StaleReferenceError,
    _ax_properties,
    _ax_value,
    _element_actions,
)


def test_reference_index_preserves_live_nodes_and_drops_missing_nodes():
    index = ReferenceIndex()
    first = ElementReference("", 42, "button", "BUTTON", ("click",))

    first_snapshot = index.reconcile([first])
    reference = first_snapshot[42].reference
    second_snapshot = index.reconcile([first])

    assert second_snapshot[42].reference == reference
    index.reconcile([])
    with pytest.raises(StaleReferenceError, match="Unknown or stale"):
        index.get(reference)


def test_reference_index_assigns_session_scoped_sequential_ids():
    index = ReferenceIndex()

    result = index.reconcile(
        [
            ElementReference("", 1, "button", "BUTTON", ("click",)),
            ElementReference("", 2, "textbox", "INPUT", ("type",)),
        ]
    )

    assert result[1].reference == "e1"
    assert result[2].reference == "e2"
    index.invalidate()
    assert index.reconcile(
        [ElementReference("", 1, "button", "BUTTON", ("click",))]
    )[1].reference == "e3"


def test_element_actions_follow_accessible_role_and_native_tag():
    assert "click" in _element_actions("button", "BUTTON", {})
    assert "type" in _element_actions("textbox", "INPUT", {})
    assert "select" in _element_actions("combobox", "SELECT", {})
    assert _element_actions("slider", "INPUT", {}) == ("click", "press_key")
    assert _element_actions("textbox", "TEXTAREA", {}) == ("type", "press_key")
    assert _element_actions("text field", "DIV", {"editable": "plaintext"}) == (
        "type",
        "press_key",
    )
    assert _element_actions("generic", "DIV", {}) == ()


def test_ax_value_reads_cdp_values_and_handles_missing_values():
    node = {
        "name": {"type": "computedString", "value": "Search"},
        "value": {"type": "string", "value": "selenium"},
    }

    assert _ax_value(node, "name") == "Search"
    assert _ax_value(node, "value") == "selenium"
    assert _ax_value(node, "description") is None


def test_ax_properties_extracts_only_accessibility_states():
    node = {
        "properties": [
            {"name": "checked", "value": {"type": "boolean", "value": True}},
            {"name": "disabled", "value": {"type": "boolean", "value": False}},
            {"name": "level", "value": {"type": "integer", "value": 2}},
            {"name": "ignoredInternalProperty", "value": {"value": "internal"}},
        ]
    }

    assert _ax_properties(node) == {"checked": True, "disabled": False, "level": 2}


def test_browser_starts_headless_and_closes_driver(monkeypatch):
    driver = Mock()
    created: dict[str, object] = {}

    def create_driver(*, options: Options, service: object) -> Mock:
        created["options"] = options
        created["service"] = service
        return driver

    monkeypatch.setattr("selenium_mcp_server.browser.webdriver.Chrome", create_driver)
    session = BrowserSession()

    assert session.driver is driver
    assert "--headless=new" in created["options"].arguments
    session.close()
    driver.quit.assert_called_once_with()
    assert session._driver is None


def test_browser_settings_configure_headed_mode_and_explicit_binary(monkeypatch, tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.write_bytes(b"")
    driver = Mock()
    created: dict[str, object] = {}

    def create_driver(*, options: Options, service: object) -> Mock:
        created["options"] = options
        return driver

    monkeypatch.setattr("selenium_mcp_server.browser.webdriver.Chrome", create_driver)
    session = BrowserSession(BrowserSettings(headless=False, binary=str(executable)))

    assert session.driver is driver
    assert "--headless=new" not in created["options"].arguments
    assert created["options"].binary_location == str(executable)


def test_chromium_uses_discovered_executable_when_no_binary_is_given(monkeypatch):
    driver = Mock()
    created: dict[str, object] = {}

    def create_driver(*, options: Options, service: object) -> Mock:
        created["options"] = options
        return driver

    monkeypatch.setattr("selenium_mcp_server.browser.webdriver.Chrome", create_driver)
    monkeypatch.setattr("selenium_mcp_server.browser.shutil.which", lambda _name: "chromium.exe")
    monkeypatch.setattr("selenium_mcp_server.browser.Path.is_file", lambda _path: True)
    session = BrowserSession(BrowserSettings(browser="chromium"))

    assert session.driver is driver
    assert created["options"].binary_location == "chromium.exe"


def test_chromium_reports_missing_executable(monkeypatch):
    monkeypatch.setattr("selenium_mcp_server.browser.shutil.which", lambda _name: None)
    session = BrowserSession(BrowserSettings(browser="chromium"))

    with pytest.raises(BrowserAutomationError, match="no chromium executable"):
        _ = session.driver


def test_browser_binary_path_is_validated_before_starting_driver(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "selenium_mcp_server.browser.webdriver.Chrome",
        Mock(side_effect=AssertionError("driver should not start")),
    )
    session = BrowserSession(BrowserSettings(binary=str(tmp_path / "missing.exe")))

    with pytest.raises(BrowserAutomationError, match="does not exist"):
        _ = session.driver


def test_snapshot_projects_accessibility_tree_and_actionable_reference(monkeypatch):
    driver = Mock()
    driver.current_url = "https://example.com/"
    driver.title = "Example"
    driver.execute_script.return_value = None
    nodes = [
        {
            "nodeId": "1",
            "role": {"value": "RootWebArea"},
            "name": {"value": "Example"},
            "childIds": ["2"],
        },
        {
            "nodeId": "2",
            "parentId": "1",
            "role": {"value": "button"},
            "name": {"value": "Continue"},
            "backendDOMNodeId": 42,
            "properties": [
                {"name": "disabled", "value": {"value": False}},
                {"name": "ignoredInternalProperty", "value": {"value": "ignored"}},
            ],
        },
    ]

    def execute_cdp_cmd(command, params):
        if command == "Accessibility.getFullAXTree":
            return {"nodes": nodes}
        if command == "DOM.describeNode":
            return {"node": {"nodeName": "BUTTON"}}
        if command == "DOM.resolveNode":
            return {"object": {"objectId": "button-object"}}
        if command == "Runtime.callFunctionOn":
            return {"result": {"value": True}}
        raise AssertionError(f"Unexpected CDP command: {command} {params}")

    driver.execute_cdp_cmd.side_effect = execute_cdp_cmd
    session = BrowserSession()
    session._driver = driver

    snapshot = session.snapshot()

    assert snapshot["url"] == "https://example.com/"
    assert snapshot["title"] == "Example"
    assert snapshot["tree"] == [
        {
            "role": "RootWebArea",
            "name": "Example",
            "children": [
                {
                    "role": "button",
                    "name": "Continue",
                    "children": [],
                    "states": {"disabled": False},
                    "ref": "e1",
                    "actions": ["click", "press_key"],
                }
            ],
        }
    ]


def test_action_resolution_rejects_unknown_reference_before_browser_lookup(monkeypatch):
    driver = Mock()
    session = BrowserSession()
    session._driver = driver
    monkeypatch.setattr(session, "_sync_document", lambda: None)

    with pytest.raises(StaleReferenceError, match="Unknown or stale"):
        session.click("unknown")

    driver.execute_script.assert_not_called()


def test_action_resolution_rejects_reference_to_missing_dom_element(monkeypatch):
    driver = Mock()
    driver.execute_script.return_value = None
    session = BrowserSession()
    session._driver = driver
    session._references.reconcile(
        [ElementReference("", 42, "button", "BUTTON", ("click",))]
    )
    monkeypatch.setattr(session, "_sync_document", lambda: None)
    reference = session._references.get("e1").reference

    with pytest.raises(StaleReferenceError, match="stale or not actionable"):
        session.click(reference)


def test_action_resolution_rejects_disabled_element(monkeypatch):
    element = Mock()
    element.is_displayed.return_value = True
    element.is_enabled.return_value = False
    driver = Mock()
    driver.execute_script.return_value = element
    session = BrowserSession()
    session._driver = driver
    session._references.reconcile(
        [ElementReference("", 42, "button", "BUTTON", ("click",))]
    )
    monkeypatch.setattr(session, "_sync_document", lambda: None)

    with pytest.raises(BrowserAutomationError, match="Element is disabled"):
        session.click("e1")


def test_action_resolution_rejects_incompatible_action_before_lookup(monkeypatch):
    driver = Mock()
    session = BrowserSession()
    session._driver = driver
    session._references.reconcile(
        [ElementReference("", 42, "button", "BUTTON", ("click",))]
    )
    monkeypatch.setattr(session, "_sync_document", lambda: None)

    with pytest.raises(BrowserAutomationError, match="does not support select"):
        session.select_option("e1", "pear")

    driver.execute_script.assert_not_called()


def test_tab_ids_remain_stable_and_are_pruned_after_closing_tab():
    driver = Mock()
    driver.window_handles = ["window-1", "window-2"]
    driver.current_window_handle = "window-1"
    driver.current_url = "https://example.com/"
    driver.title = "Example"
    driver.switch_to = Mock()
    session = BrowserSession()
    session._driver = driver

    first_listing = session.list_tabs()
    second_listing = session.list_tabs()

    assert first_listing["tabs"][0]["id"] == "t1"
    assert first_listing["tabs"][1]["id"] == "t2"
    assert second_listing["tabs"][0]["id"] == "t1"
    assert second_listing["tabs"][1]["id"] == "t2"
    assert first_listing["active"] == "t1"


def test_unknown_tab_references_do_not_switch_or_close_browser_tabs():
    driver = Mock()
    driver.window_handles = ["window-1"]
    session = BrowserSession()
    session._driver = driver

    with pytest.raises(ValueError, match="Unknown tab reference"):
        session.switch_tab("unknown")
    with pytest.raises(ValueError, match="Unknown tab reference"):
        session.close_tab("unknown")

    driver.switch_to.window.assert_not_called()
    driver.close.assert_not_called()


def test_close_tab_preserves_a_different_active_tab(monkeypatch):
    driver = Mock()
    driver.window_handles = ["window-1", "window-2"]
    driver.current_window_handle = "window-1"
    driver.switch_to = Mock()
    driver.execute_script.return_value = "document-token"
    session = BrowserSession()
    session._driver = driver
    session._tab_ids = {"window-1": "t1", "window-2": "t2"}
    session._document_token = "document-token"
    monkeypatch.setattr(session, "_sync_document", lambda: None)

    assert session.close_tab("t2") == {"closed": "t2"}
    driver.switch_to.window.assert_called_with("window-1")
    driver.close.assert_called_once_with()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///tmp/page.html",
        "/relative/path",
        "https:///missing-host",
    ],
)
def test_navigation_rejects_non_http_or_invalid_urls(url):
    with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
        BrowserSession._validate_url(url)


def test_wait_accepts_the_documented_range(monkeypatch):
    sleeps = []
    monkeypatch.setattr("selenium_mcp_server.browser.time.sleep", sleeps.append)

    assert BrowserSession.wait(0.5) == {"waited": 0.5}
    assert sleeps == [0.5]


@pytest.mark.parametrize("seconds", [-1, MAX_WAIT_SECONDS + 1, math.inf, math.nan])
def test_wait_rejects_out_of_range_or_non_finite_values(seconds):
    with pytest.raises(ValueError, match="seconds must be between"):
        BrowserSession.wait(seconds)
