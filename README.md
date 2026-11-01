# Selenium Autopilot

Selenium Autopilot is a Python command-line tool and Selenium helper library for browser-test automation. It can turn written requirements into a structured test plan, generate a pytest/Selenium project from a reviewed plan, and analyze test failures to suggest locator repairs. Generated tests and repair suggestions require human review; the tool does not change your application or automatically apply fixes.

## What you can do

- **Plan tests:** Convert acceptance criteria, and optionally relevant source files, into prioritized test scenarios and a JSON plan.
- **Generate tests:** Create pytest tests and Selenium Page Objects from a reviewed plan.
- **Investigate failures:** Classify a failure report and, for locator failures, produce a proposed code diff.
- **Run browser tests:** Use Selenium with Chrome, explicit waits, and useful failure diagnostics.
- **Report results:** Convert JUnit XML to JSON and optionally publish a test summary to a GitHub pull request.

## Requirements

- Python 3.10 or newer
- Google Chrome
- An OpenAI-compatible provider for planning, generation, and locator proposals. A compatible local provider is also supported.

You do **not** need to clone or download this repository to use the package.

## Install from PyPI

Install Selenium Autopilot in the Python environment where you want to use it:

```shell
python -m pip install selenium-autopilot
```

This installs the `autopilot` command and the Python dependencies. Check that it is available with:

```shell
autopilot --help
```

## Configure an AI provider

Planning, test generation, and locator proposals use an OpenAI-compatible chat-completions API. By default, the tool uses the OpenAI API URL and the `gpt-4o-mini` model. Set your API key as an environment variable before running those commands.

PowerShell:

```powershell
$env:AUTOPILOT_LLM_API_KEY = "your-api-key"
```

macOS or Linux:

```shell
export AUTOPILOT_LLM_API_KEY="your-api-key"
```

You can also configure a different endpoint and model with `AUTOPILOT_LLM_BASE_URL` and `AUTOPILOT_LLM_MODEL`. For example, a local OpenAI-compatible service might use:

```text
AUTOPILOT_LLM_BASE_URL=http://localhost:11434/v1
AUTOPILOT_LLM_MODEL=your-local-model
```

Local HTTP is supported only for loopback addresses; remote providers must use HTTPS. Never put API keys, passwords, or other secrets in requirements, source files, or generated tests. Requirements and any source files you pass to `plan` are sent to the configured provider, so only share content you are permitted to share.

## 1. Write your requirements

Create a Markdown file describing what users should be able to do and what the application should show. Be specific about preconditions, actions, and expected results. Use an approved test environment and synthetic test data.

For example, save this as `requirements.md`:

```markdown
# Sign-in requirements

- Given a valid test account, submitting its credentials signs the user in.
- After successful sign-in, the dashboard is displayed.
- Invalid credentials do not sign the user in.
- The application displays an error when sign-in is rejected.
```

If a behavior or expected message is not defined, say so. The planner records ambiguities rather than deciding what your application should do.

## 2. Create and review a test plan

```shell
autopilot plan --requirements requirements.md --output artifacts/test-plan.json
```

The plan contains a summary, prioritized scenarios, preconditions, steps, expected results, ambiguities, and risks. You can provide relevant source files as additional context; repeat `--source` for each file:

```shell
autopilot plan --requirements requirements.md --source src/login.py --output artifacts/test-plan.json
```

Review the plan before generating tests. If the output already exists, the command will not replace it unless you explicitly add `--overwrite`.

## 3. Generate a pytest/Selenium project

Generate tests from the reviewed plan:

```shell
autopilot generate --plan artifacts/test-plan.json --output generated_tests
```

The output includes a `tests` folder, Page Objects, a Chrome WebDriver fixture, and project setup files. Generated URLs, locators, test data, and assertions may need changes for your application. Review every generated file before running it; generation does not guarantee correct tests.

Install the generated project's dependencies and run its tests:

```shell
cd generated_tests
python -m pip install pytest selenium
python -m pytest
```

Use a non-production environment and approved test accounts. The generated fixture runs Chrome in headless mode. If the output already contains generated files, Autopilot refuses to replace them unless you pass `--overwrite`; review the existing files first.

## 4. Analyze a failure and request a locator proposal

To save browser diagnostics and a failure report when a test fails, run pytest with the Autopilot plugin enabled:

```shell
python -m pytest -p autopilot.pytest_plugin --junitxml=junit.xml
```

For failures that have a `driver` fixture, the plugin saves a screenshot, DOM snapshot, browser metadata, and `failure-report.json` under `artifacts/diagnostics/` by default. You can change that location with `AUTOPILOT_ARTIFACTS_DIR`.

Classify a failure without an AI provider:

```shell
autopilot analyze --report artifacts/diagnostics/path-to-failure/failure-report.json --output artifacts/failure-analysis.json
```

For a **locator-drift** failure, request a proposed locator change:

```shell
autopilot heal --report artifacts/diagnostics/path-to-failure/failure-report.json --source tests/test_login.py --output artifacts/healing-proposal.json
```

The failure report must include the current `locator_strategy` and `locator_value` (for example, `"css"` and `"#submit"`). Add these fields to the report if they were not captured. The source file must contain the old locator as a single string value.

Healing creates a JSON proposal and diff; it does **not** edit the source file, change assertions, or rerun tests. The command-line workflow does not check the proposed locator against a live browser, so its uniqueness is reported as unchecked. Review the evidence and diff, verify the locator yourself, and apply an accepted change manually before rerunning the affected test and relevant regressions. Locator healing is not intended to fix application defects, invalid test data, or environment problems.

## Other commands

- `autopilot report --junit junit.xml --output artifacts/test-results.json` converts pytest's JUnit XML into a structured JSON report.
- `autopilot github-report --help` shows options for publishing or updating a test-summary comment on a pull request. Set `GITHUB_TOKEN` and provide the repository and pull-request details.

Run `autopilot --help` or `autopilot <command> --help` for all available options. Output files are not overwritten by default; use `--overwrite` only after reviewing existing outputs.
