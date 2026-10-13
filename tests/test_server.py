from selenium_mcp_server.server import create_server


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
