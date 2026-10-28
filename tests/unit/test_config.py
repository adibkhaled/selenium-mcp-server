import os

from autopilot.config import load_environment


def test_load_environment_reads_dotenv_without_overwriting_existing_values(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AUTOPILOT_LLM_MODEL=from-dotenv\nAUTOPILOT_LLM_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOPILOT_LLM_MODEL", raising=False)
    monkeypatch.setenv("AUTOPILOT_LLM_API_KEY", "existing-key")

    load_environment()

    assert os.environ["AUTOPILOT_LLM_MODEL"] == "from-dotenv"
    assert os.environ["AUTOPILOT_LLM_API_KEY"] == "existing-key"
