from __future__ import annotations

import asyncio
import os
import shutil
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


LIVE_SITE_URL = "https://www.adibqasolutions.com/"


def _find_node(nodes, role, name):
    for node in nodes:
        if node.get("role") == role and node.get("name") == name:
            return node
        found = _find_node(node.get("children", []), role, name)
        if found:
            return found
    return None


def _structured_content(result):
    if result.isError:
        messages = [
            item.text
            for item in result.content
            if getattr(item, "type", None) == "text"
        ]
        pytest.fail(
            f"The live-site MCP tool call failed for {LIVE_SITE_URL}: "
            f"{'; '.join(messages) or 'no error details returned'}"
        )
    if result.structuredContent is None:
        pytest.fail(f"The live-site MCP tool returned no structured content for {LIVE_SITE_URL}.")
    return result.structuredContent


@pytest.mark.live_site
def test_live_site_accessible_home_page_smoke():
    chrome_candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    if not any(path and os.path.isfile(path) for path in chrome_candidates):
        pytest.skip("Chrome or Chromium is not installed; the live-site test requires a local browser.")

    async def exercise_live_site():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "selenium_mcp_server"],
            env=os.environ.copy(),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                navigation = _structured_content(
                    await client.call_tool("navigate", {"url": LIVE_SITE_URL})
                )
                assert navigation["url"].startswith("https://www.adibqasolutions.com/")

                snapshot = _structured_content(await client.call_tool("snapshot", {}))
                assert snapshot["title"] == "Adib Bin Khaled | QA & Test Automation Engineer"
                assert _find_node(snapshot["tree"], "heading", "Adib Khaled") is not None
                assert _find_node(snapshot["tree"], "button", "Open menu") is not None

    asyncio.run(exercise_live_site())
