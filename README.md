## Selenium Autopilot (Phase 1)

The `autopilot` Python package is a deterministic Selenium wrapper that can be used independently of the MCP stdio protocol. It currently provides a headless Chrome lifecycle, URL navigation (including paths relative to a configured `base_url`), role/name, label, test-ID, CSS, and XPath locators, retrying explicit-wait assertions, and opt-in screenshot/DOM/metadata diagnostics. Accessible-name matching is a practical Selenium XPath implementation, not a browser-native Playwright API.

```python
from autopilot import Autopilot, AutopilotConfig, capture_diagnostics

config = AutopilotConfig(base_url="https://adibqasolutions.com", timeout=10)
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

Every proposal requires human review. A generated diff is not a validated repair: `applied` remains false and `validation` remains `not_run`. The system does not remove or alter assertions, change expected behavior, or claim that a test passed. Review the report and candidate against approved requirements and DOM evidence, apply any accepted change manually, then run the affected test and relevant regressions yourself.

## GitHub Actions and Pull Request Reports (Phase 5)

The [Selenium Autopilot Tests workflow](.github/workflows/selenium-tests.yml) runs on pull request updates and can also be started manually with `workflow_dispatch`. It runs the non-live-site test suite on Python 3.11 with headless Chrome, writes JUnit XML and a normalized report, and uploads reports plus any Selenium screenshots, DOM snapshots, and failure metadata as a seven-day artifact.

For pull requests, a separate reporting job publishes or updates one summary comment using the GitHub REST API. It requires only `contents: read` for checkout and `issues: write` for issue comments. The test job runs untrusted pull request code with no write permission or application secrets; the comment job checks out the trusted base revision and does not execute pull request code. The workflow derives the overall job status from GitHub Actions, and treats JUnit content as an artifact when displaying counts. It does not create repair commits, push branches, open pull requests, or merge changes.

The comment contains test counts and failing test names, not stack traces or raw failure messages. Full diagnostic details are available to repository users with access to the Actions artifact. Diagnostic artifacts can contain page DOM and test environment information; avoid using real credentials or sensitive production data in CI.

If pull request comments are not published for fork contributions, check repository/organization Actions policy for `GITHUB_TOKEN` write access to pull requests from forks. Do not enable write access for the test job; only the isolated report job needs `issues: write`. Repositories that prohibit write tokens for fork workflows can still view the test report and diagnostics in the workflow artifacts.

Locally, convert JUnit output with `uv run autopilot report --junit artifacts/junit.xml --output artifacts/test-results.json`. Publish a report with `uv run autopilot github-report --report artifacts/test-results.json --repository owner/repo --pull-request 123`; provide a short-lived token with issue-comment permission as `GITHUB_TOKEN`. The command updates its existing marked comment rather than posting duplicates. No GitHub token is required to run tests or parse JUnit locally.

Phase 5 does not create GitHub Actions runs through the API or open repair pull requests. Healing proposals remain review-only and must be applied and validated manually before they could be considered for a proposed PR.

## Regression Validation and Integration Tests (Phase 6)

The regression suite covers both Python and TypeScript. Integration tests exercise the offline requirements-to-generated-project-to-JUnit-report flow and the failure-diagnosis-to-review-only-healing flow. A separate Selenium integration test drives a temporary local HTML page in headless Chrome; it does not access a live website or require model credentials. Local runs skip only this browser test when Chrome/WebDriver cannot start. CI sets `AUTOPILOT_REQUIRE_BROWSER=1`, so a missing or unusable browser fails the job instead of silently skipping the check.

Install the Python and Node dependencies, then run the same checks locally:

```powershell
uv sync --locked
npm ci
uv run pytest -m "not live_site"
npm run test:agent-specs
uv lock --check
uv build
```

The non-live-site pytest selection includes `integration` tests and excludes only tests explicitly marked `live_site`. Integration coverage uses a fake WebDriver to execute generated project code, then validates the resulting JUnit report; the local-page browser test separately verifies real locator, input, click, and wait behavior when Chrome is available. The GitHub Actions workflow runs the Python suite, TypeScript parser tests, lockfile check, and package build, and uploads test diagnostics even when a test fails.