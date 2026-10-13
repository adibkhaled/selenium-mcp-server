import asyncio
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


HTML = b"""<!doctype html>
<html lang="en">
  <head><title>Browser fixture</title></head>
  <body>
    <label for="search">Search</label>
    <input id="search" type="text">
    <label for="fruit">Fruit</label>
    <select id="fruit">
      <option value="apple">Apple</option>
      <option value="pear">Pear</option>
    </select>
    <button id="submit" onclick="document.querySelector('h1').textContent='Done'">Submit</button>
    <h1>Status</h1>
  </body>
</html>"""


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, _format, *args):
        return


def _content(result):
    if result.isError:
        message = "\n".join(getattr(item, "text", "") for item in result.content)
        raise AssertionError(f"MCP tool returned an error: {message}")
    if result.structuredContent is not None:
        return result.structuredContent
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    raise AssertionError("MCP tool returned no structured or text content.")


def _find_node(nodes, role, name):
    for node in nodes:
        if node.get("role") == role and node.get("name") == name and node.get("ref"):
            return node
        found = _find_node(node.get("children", []), role, name)
        if found:
            return found
    return None


@pytest.mark.integration
def test_stdio_server_automates_accessible_chrome_page():
    chrome_candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    if not any(path and os.path.isfile(path) for path in chrome_candidates):
        pytest.skip("Chrome is not installed; the stdio browser integration test needs Chrome.")

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{http_server.server_port}/"

    async def exercise_server():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "selenium_mcp_server"],
            env=os.environ.copy(),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert "snapshot" in {tool.name for tool in tools.tools}

                navigation = _content(await client.call_tool("navigate", {"url": url}))
                assert navigation["url"] == url
                invalid_navigation = await client.call_tool(
                    "navigate",
                    {"url": "ftp://127.0.0.1/"},
                )
                assert invalid_navigation.isError

                snapshot = _content(await client.call_tool("snapshot", {}))
                assert snapshot["title"] == "Browser fixture"
                search = _find_node(snapshot["tree"], "textbox", "Search")
                select = _find_node(snapshot["tree"], "combobox", "Fruit")
                button = _find_node(snapshot["tree"], "button", "Submit")
                assert search and select and button

                stable_snapshot = _content(await client.call_tool("snapshot", {}))
                stable_search = _find_node(stable_snapshot["tree"], "textbox", "Search")
                assert stable_search["ref"] == search["ref"]

                _content(
                    await client.call_tool(
                        "type_text",
                        {"ref": search["ref"], "text": "selenium"},
                    )
                )
                _content(
                    await client.call_tool(
                        "press_key",
                        {"ref": search["ref"], "key": "ENTER"},
                    )
                )
                _content(
                    await client.call_tool(
                        "select_option",
                        {"ref": select["ref"], "value": "pear"},
                    )
                )
                invalid_action = await client.call_tool(
                    "select_option",
                    {"ref": button["ref"], "value": "pear"},
                )
                assert invalid_action.isError
                _content(await client.call_tool("click", {"ref": button["ref"]}))
                _content(await client.call_tool("wait", {"seconds": 0.0}))

                tabs = _content(await client.call_tool("list_tabs", {}))
                unknown_tab = await client.call_tool("switch_tab", {"tab_id": "unknown"})
                assert unknown_tab.isError
                unknown_close = await client.call_tool("close_tab", {"tab_id": "unknown"})
                assert unknown_close.isError
                new_tab = _content(await client.call_tool("open_tab", {"url": url}))
                assert len(_content(await client.call_tool("list_tabs", {}))["tabs"]) == 2
                _content(
                    await client.call_tool(
                        "switch_tab",
                        {"tab_id": tabs["active"]},
                    )
                )
                _content(await client.call_tool("close_tab", {"tab_id": new_tab["id"]}))

                invalidated = await client.call_tool("navigate", {"url": url})
                _content(invalidated)
                stale_result = await client.call_tool("click", {"ref": search["ref"]})
                assert stale_result.isError

    try:
        asyncio.run(exercise_server())
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2)
