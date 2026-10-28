# Selenium Autopilot

Selenium Autopilot helps you create and run browser tests for your web application. It creates a test plan from your written requirements, generates pytest tests, and runs them in Chrome. It does not host or change your application.

## What you need

- Windows, [Visual Studio Code](https://code.visualstudio.com/), and its Python extension
- Python 3.10 or newer and [Google Chrome](https://www.google.com/chrome/)
- [Git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/)
- An OpenAI-compatible AI provider for creating plans and tests (a local provider is also supported)

## Download and open in VS Code

Download the ZIP from the [GitHub repository](https://github.com/adibkhaled/selenium-mcp-server) using **Code > Download ZIP**, then extract it. In VS Code, choose **File > Open Folder** and select the extracted project folder.

Or clone it in a terminal:

```powershell
git clone https://github.com/adibkhaled/selenium-mcp-server.git
code selenium-mcp-server
```

In the VS Code terminal, install the project dependencies:

```powershell
uv sync
```

## Create and run tests for your web app

1. Write down the page URL and the user actions and results you want to test. Include acceptance criteria and use a test environment, not production. Do not include real passwords or other secrets. You can start with [the sample requirements](examples/requirements/login.md).
2. Configure an AI provider in the VS Code terminal. For the default OpenAI-compatible provider, set your model and API key (keep the key private):

   ```powershell
   $env:AUTOPILOT_LLM_MODEL = "gpt-4o-mini"
   $env:AUTOPILOT_LLM_API_KEY = "your-api-key"
   ```

   For a local provider, set `AUTOPILOT_LLM_BASE_URL` and `AUTOPILOT_LLM_MODEL` instead. For example, a local OpenAI-compatible service might use `http://localhost:11434/v1`.
3. Create a test plan. Replace the sample path with your requirements file:

   ```powershell
   uv run autopilot plan --requirements examples/requirements/login.md --output artifacts/test-plan.json
   ```

4. Review the plan, then generate the tests:

   ```powershell
   uv run autopilot generate --plan artifacts/test-plan.json --output generated_tests
   ```

5. Review the generated tests. Update any example URLs and test data for your approved test environment, then run them:

   ```powershell
   uv run --directory generated_tests pytest
   ```

Planning and generation require the configured provider. Review generated tests before running them; generation does not guarantee that they are correct. To rerun a command that would overwrite an existing output, first review the existing files and use its `--overwrite` option.

For the other available features and development phases, see [FEATURES.txt](FEATURES.txt).
