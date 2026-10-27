from __future__ import annotations

import argparse
import functools
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, TypeVar, TypedDict

from mcp.server.fastmcp import Context, FastMCP

from .browser import BrowserSession, BrowserSettings


logger = logging.getLogger(__name__)
Result = TypeVar("Result")


class ServerContext(TypedDict):
    browser: BrowserSession


def _log_tool_call(func: Callable[..., Result]) -> Callable[..., Result]:
    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Result:
        tool_name = func.__name__
        logger.info("MCP tool %s started", tool_name)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            logger.error("MCP tool %s failed (%s)", tool_name, type(exc).__name__)
            raise
        logger.info("MCP tool %s completed", tool_name)
        return result

    return wrapped


def create_server(settings: BrowserSettings | None = None) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[ServerContext]:
        browser = BrowserSession(settings)
        try:
            yield {"browser": browser}
        finally:
            logger.info("Closing browser session")
            browser.close()

    server = FastMCP("selenium-mcp-server", lifespan=lifespan)

    def session_from(ctx: Context) -> BrowserSession:
        return ctx.request_context.lifespan_context["browser"]

    @server.tool()
    @_log_tool_call
    def navigate(url: str, ctx: Context) -> dict[str, str]:
        """Navigate to an HTTP(S) URL and return the final URL and page title."""
        return session_from(ctx).navigate(url)

    @server.tool()
    @_log_tool_call
    def snapshot(ctx: Context) -> dict[str, Any]:
        """Return the current page's Chrome accessibility tree and actionable element references."""
        return session_from(ctx).snapshot()

    @server.tool()
    @_log_tool_call
    def click(ref: str, ctx: Context) -> dict[str, str]:
        """Click an actionable element reference from the latest snapshot."""
        return session_from(ctx).click(ref)

    @server.tool()
    @_log_tool_call
    def type_text(ref: str, text: str, ctx: Context) -> dict[str, str]:
        """Type text into an editable element reference from the latest snapshot."""
        return session_from(ctx).type_text(ref, text)

    @server.tool()
    @_log_tool_call
    def select_option(ref: str, value: str, ctx: Context) -> dict[str, str]:
        """Select an option value in a native select element."""
        return session_from(ctx).select_option(ref, value)

    @server.tool()
    @_log_tool_call
    def press_key(ref: str, key: str, ctx: Context) -> dict[str, str]:
        """Send a Selenium key name (for example ENTER) or single character to an element."""
        return session_from(ctx).press_key(ref, key)

    @server.tool()
    @_log_tool_call
    def wait(seconds: float, ctx: Context) -> dict[str, float]:
        """Pause automation for 0 to 30 seconds."""
        return session_from(ctx).wait(seconds)

    @server.tool()
    @_log_tool_call
    def list_tabs(ctx: Context) -> dict[str, Any]:
        """List open browser tabs and identify the active tab."""
        return session_from(ctx).list_tabs()

    @server.tool()
    @_log_tool_call
    def open_tab(ctx: Context, url: str | None = None) -> dict[str, str]:
        """Open a browser tab, optionally navigating it to an HTTP(S) URL."""
        return session_from(ctx).open_tab(url)

    @server.tool()
    @_log_tool_call
    def switch_tab(tab_id: str, ctx: Context) -> dict[str, str]:
        """Switch to a tab reference returned by list_tabs or open_tab."""
        return session_from(ctx).switch_tab(tab_id)

    @server.tool()
    @_log_tool_call
    def close_tab(tab_id: str, ctx: Context) -> dict[str, str]:
        """Close a tab reference without closing the last browser tab."""
        return session_from(ctx).close_tab(tab_id)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Selenium browser automation MCP server")
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome")
    parser.add_argument("--browser-binary", help="Path to a Chrome or Chromium executable")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="Logging verbosity (default: INFO); logs are written to stderr",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of using headless mode",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("Starting selenium-mcp-server with stdio transport")
    create_server(
        BrowserSettings(
            browser=args.browser,
            headless=not args.headed,
            binary=args.browser_binary,
        )
    ).run(transport="stdio")
    logger.info("selenium-mcp-server stopped")


if __name__ == "__main__":
    main()
