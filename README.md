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

The workspace agents in `.github/agents/` include a Selenium automation orchestrator and focused Test Planner, Test Generator, and Test Healer specialists. The specialist agents have restricted tool access appropriate to their roles. Their definitions describe intended workflows; they do not imply that planner, generator, healer, or GitHub functionality exists unless implemented in the corresponding phase.

Install Node.js 20 or newer, then run:

```powershell
npm ci
npm run build:agent-specs
npm run test:agent-specs
```

The parser tests use Node's built-in test runner and need no model or API credentials.

The MCP server remains a separate browser interface; MCP-backed journey recording is not implemented.

## Test Planning and Generation (Phase 3)

The `autopilot` CLI can use an OpenAI-compatible chat-completions provider to convert requirements and optional source files into a validated plan, then generate a separate pytest/Selenium project with Page Objects from that plan. Plans follow [test-plan.schema.json](schemas/test-plan.schema.json). Planning and generation use a provider interface, so tests can mock the provider and do not need API credentials.

Configure a cloud or local provider with environment variables. Remote endpoints must use HTTPS; local HTTP is permitted for loopback hosts. The default endpoint is OpenAI-compatible (`https://api.openai.com/v1`).

```powershell
$env:AUTOPILOT_LLM_BASE_URL = "http://localhost:11434/v1"
$env:AUTOPILOT_LLM_MODEL = "your-local-model"
# Optional for providers that require authentication:
$env:AUTOPILOT_LLM_API_KEY = "your-provider-key"

uv run autopilot plan `
  --requirements examples/requirements/login.md `
  --source src/your_app/auth.py `
  --output artifacts/test-plan.json

# Review and approve the generated JSON before using it as a generation input.
uv run autopilot generate `
  --plan artifacts/test-plan.json `
  --output generated_tests
```

`--source` may be repeated. Planning sends the supplied requirement and source text to the configured provider, so do not include credentials, secrets, or data you are not permitted to share; use a local endpoint when required by your data-handling policy. Generated code is syntax-checked, restricted to Page Object/test paths and an import allowlist, and written without overwriting existing files unless `--overwrite` is explicitly passed. The tool does not execute generated code. Review generated locators, URLs, test data, and assertions before running the standalone project; generated behavior is not guaranteed correct by static validation.

Install the project's Python environment with `uv sync`, configure Chrome, then run generated tests from the output directory using `uv run --directory generated_tests pytest`. The standalone generated project also includes a `pyproject.toml` and a headless Chrome fixture.

The planner records ambiguities rather than choosing expected behavior. The generator creates tests only from the supplied plan.

## Failure Analysis and Healing Proposals (Phase 4)

Provide a failure report as JSON with `exception_type` and `message`; optional fields include `traceback`, `browser`, `url`, `failed_action`, test identity, screenshot/DOM paths, `locator_strategy` and `locator_value`, `assertion_failure`, `test_data_validated`, and `browser_started`.

```powershell
uv run autopilot analyze `
  --report artifacts/failure.json `
  --output artifacts/failure-analysis.json

uv run autopilot heal `
  --report artifacts/failure.json `
  --source tests/test_login.py `
  --output artifacts/healing-proposal.json
```

`analyze` is deterministic and does not contact an LLM. It classifies evidence as locator drift, synchronization, application defect, invalid test data, environment, or unknown, and returns confidence, evidence, and next steps in the shape described by [failure-analysis.schema.json](schemas/failure-analysis.schema.json). `heal` is limited to locator-drift reports with a current locator; the provider is asked for an evidence-based candidate using the source and, when provided, DOM snapshot. The proposal follows [healing-proposal.schema.json](schemas/healing-proposal.schema.json), shows a diff made by replacing exactly one Python string literal matching the old locator value, and never modifies source or runs tests. Without an attached live WebDriver, uniqueness is explicitly `not_checked` and confidence is capped. With a WebDriver, the candidate must match exactly one element or proposal creation fails.

Every proposal requires human review. A generated diff is not a validated repair: `applied` remains false and `validation` remains `not_run`. The system does not remove or alter assertions, change expected behavior, or claim that a test passed. Review the report and candidate against approved requirements and DOM evidence, apply any accepted change manually, then run the affected test and relevant regressions yourself. GitHub integration and CI reporting are not implemented yet.