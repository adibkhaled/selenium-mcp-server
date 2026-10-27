import logging

import pytest

from selenium_mcp_server.server import _log_tool_call, create_server


def test_server_registers_browser_and_tab_tools():
    server = create_server()

    assert {tool.name for tool in server._tool_manager.list_tools()} == {
        "navigate",
        "snapshot",
        "click",
        "type_text",
        "select_option",
        "press_key",
        "wait",
        "list_tabs",
        "open_tab",
        "switch_tab",
        "close_tab",
    }


def test_log_tool_call_records_success(caplog):
    @_log_tool_call
    def example_tool():
        return "done"

    with caplog.at_level(logging.INFO, logger="selenium_mcp_server.server"):
        assert example_tool() == "done"

    assert "MCP tool example_tool started" in caplog.text
    assert "MCP tool example_tool completed" in caplog.text


def test_log_tool_call_records_failure_without_arguments(caplog):
    @_log_tool_call
    def example_tool(secret):
        raise ValueError(f"invalid value: {secret}")

    with caplog.at_level(logging.ERROR, logger="selenium_mcp_server.server"):
        with pytest.raises(ValueError, match="invalid value"):
            example_tool("sensitive input")

    assert "MCP tool example_tool failed (ValueError)" in caplog.text
    assert "sensitive input" not in caplog.text
