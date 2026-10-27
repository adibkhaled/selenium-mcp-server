## Selenium Autopilot (Phase 1)

The `autopilot` Python package is a deterministic Selenium wrapper that can be used independently of the MCP stdio protocol. It currently provides a headless Chrome lifecycle, URL navigation (including paths relative to a configured `base_url`), role/name, label, test-ID, CSS, and XPath locators, retrying explicit-wait assertions, and opt-in screenshot/DOM/metadata diagnostics. Accessible-name matching is a practical Selenium XPath implementation, not a browser-native Playwright API.

```python
from autopilot import Autopilot, AutopilotConfig, capture_diagnostics

config = AutopilotConfig(base_url="https://example.test", timeout=10)
with Autopilot(config=config) as agent:
    agent.open("/login")
    agent.get_by_label("Email").fill("test@example.test")
    agent.get_by_role("button", "Sign in").click()
    agent.expect_url_contains("/dashboard")

# On test failure, explicitly capture evidence from an available WebDriver:
# report = capture_diagnostics(driver, "artifacts/failures", "submit login")
```

`Autopilot` starts Chrome on first use and always quits it when its context exits. The framework raises descriptive timeout errors, and strict locator resolution reports ambiguous matches rather than silently using the first result. Diagnostics are opt-in and return paths and any collection errors. Run its unit tests with `uv run pytest tests/unit`.

## Agent Specifications and Copilot Agents (Phase 2)

The TypeScript parser in `agent_specs/parse-agent-spec.ts` reads Markdown agent definitions, parses YAML front matter, validates required metadata and common field types, extracts instructions and `<example>...</example>` blocks, and normalizes Windows and Unix line endings. It parses definitions only; it does not execute agents.

The workspace agents in `.github/agents/` include a Selenium automation orchestrator and focused Test Planner, Test Generator, and Test Healer specialists. The specialist agents have restricted tool access appropriate to their roles. Their definitions describe intended workflows; they do not imply that the later AI planning, generation, healing, or GitHub integration phases are already implemented.

Install Node.js 20 or newer, then run:

```powershell
npm ci
npm run build:agent-specs
npm run test:agent-specs
```

The parser tests use Node's built-in test runner and need no model or API credentials.

This phase adds no AI provider, planner/generator/healer runtime, GitHub integration, or CLI. The MCP server remains a separate browser interface; generated test projects and MCP-backed journey recording are not implemented.