 # Selenium MCP Server

A local Model Context Protocol (MCP) server for deterministic browser automation with Selenium. It returns Chrome's structured accessibility tree and session-scoped element references; it does not use screenshots or vision models.

## Requirements

- Python 3.10 or newer
- Chrome installed, or Chromium plus its executable path
- [`uv`](https://docs.astral.sh/uv/) to install and run the project

Selenium Manager locates or downloads a compatible WebDriver. Its first use may require network access. Browser binaries are not bundled.

## Install and run

From the project directory:

```powershell
uv sync --link-mode copy
uv run selenium-mcp-server
```

The server communicates over MCP stdio; run it from an MCP client rather than as an interactive command. It starts Chrome headlessly when the first browser tool is called. Use `--headed` to show the browser window.

```text
selenium-mcp-server [--browser chrome|chromium] [--browser-binary PATH] [--headed] [--log-level LEVEL]
```

- `--browser chrome` is the default and lets Selenium Manager locate Chrome.
- `--browser chromium` selects Chromium from `PATH` where available.
- `--browser-binary PATH` explicitly selects a Chrome-compatible executable, useful for Chromium installations.
- Headless mode is the default. Add `--headed` to disable it.
- `--log-level LEVEL` sets the logging verbosity to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or `CRITICAL`. Server lifecycle and tool-call outcomes are logged to stderr; tool arguments and entered text are not logged.

## Verify setup

Start or restart the MCP client after adding the server. Confirm that the server is connected and exposes tools such as `navigate` and `snapshot`, then navigate to an HTTP(S) page and request a snapshot. The server writes MCP protocol messages to stdout, so do not add shell output or logging to that stream.

## MCP tools

| Tool | Inputs | Behavior |
| --- | --- | --- |
| `navigate` | `url` | Opens an absolute HTTP or HTTPS URL and returns the final URL and title. |
| `snapshot` | none | Returns URL, title, and a nested accessibility tree (`role`, `name`, `value`, `description`, `states`, and `children`). Actionable nodes include an opaque `ref` and supported `actions`. |
| `click` | `ref` | Clicks a current actionable element. |
| `type_text` | `ref`, `text` | Sends text to a current editable element. |
| `select_option` | `ref`, `value` | Selects a value on a native HTML `<select>`. |
| `press_key` | `ref`, `key` | Sends a Selenium key name such as `ENTER` or a single character. |
| `wait` | `seconds` | Waits for a duration from 0 through 30 seconds. |
| `list_tabs` | none | Lists open tabs with session-scoped IDs, URLs, and titles. |
| `open_tab` | optional `url` | Opens a tab, optionally navigating to an HTTP(S) URL. |
| `switch_tab` | `tab_id` | Activates a tab from `list_tabs` or `open_tab`. |
| `close_tab` | `tab_id` | Closes a tab; the last browser tab cannot be closed. |

Element references are stable across snapshots while the same DOM node remains actionable. Take a fresh snapshot after navigation or major page changes and use references from the current page. Unknown, stale, disabled, and incompatible element actions return explicit tool errors.

## Configure MCP clients

Replace `C:\\path\\to\\selenium-mcp-server` below with the absolute path to this checkout. The examples use `uv run`, which creates/synchronizes the project environment as needed. `--link-mode copy` avoids hard-link issues on some Windows and cloud-synced folders. Ensure `uv` is on the MCP client's `PATH`; otherwise set `command` to the absolute path of `uv.exe` (Windows) or `uv` (macOS/Linux). `--headed` is optional and omitted by default.

### VS Code

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "selenium": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--link-mode",
        "copy",
        "--directory",
        "C:\\path\\to\\selenium-mcp-server",
        "selenium-mcp-server",
        "--browser",
        "chrome"
      ]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "selenium": {
      "command": "uv",
      "args": [
        "run",
        "--link-mode",
        "copy",
        "--directory",
        "C:\\path\\to\\selenium-mcp-server",
        "selenium-mcp-server",
        "--browser",
        "chrome"
      ]
    }
  }
}
```

### Windsurf

Add the `selenium` entry to `~/.codeium/windsurf/mcp_config.json` under `mcpServers`. Use the same `command` and `args` as the Cursor example.

### Claude Desktop

Add the `selenium` entry to `claude_desktop_config.json` under `mcpServers`. Use the same `command` and `args` as the Cursor example, then restart Claude Desktop.

### Goose

In Goose, open the extension configuration (`goose configure`), add a command-line extension, and set its command to `uv` with these arguments:

```json
[
  "run",
  "--link-mode",
  "copy",
  "--directory",
  "C:\\path\\to\\selenium-mcp-server",
  "selenium-mcp-server",
  "--browser",
  "chrome"
]
```

Set the extension type to `stdio` and ensure the `uv` command is available to the Goose process.

### Grok

Grok product and integration surfaces do not all expose the same MCP configuration. If your Grok client or MCP host supports launching local stdio servers, add a server with command `uv` and the same arguments shown in the Cursor example. This project exposes stdio MCP only; it does not provide a remote HTTP MCP endpoint, and a native Grok configuration surface is not assumed.

### Junie

In JetBrains IDE settings, open Junie's MCP server configuration and add a local stdio server with command `uv` and the same arguments shown in the Cursor example. If Junie's configuration editor expects JSON, use the Cursor `mcpServers` entry.

## Browser and reference behavior

- Browser sessions are created lazily and closed when the MCP server process exits.
- Chrome is headless by default. For a visible browser, add `"--headed"` to the client `args`.
- To use a specific Chromium binary, use `"--browser", "chromium", "--browser-binary", "/absolute/path/to/chromium"` (use an absolute Windows path on Windows).
- Accessibility information comes from Chrome's computed accessibility tree through CDP. Frames, downloads, dialogs, network interception, remote browser services, and non-Chrome engines are not covered.
- Browser content remains local to the Selenium process. Selenium Manager may access the network to obtain a matching driver.
