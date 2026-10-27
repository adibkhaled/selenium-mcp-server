from __future__ import annotations

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """An LLM provider request failed or returned an unusable response."""


class OpenAICompatibleProvider:
    """Chat-completions provider for cloud or local OpenAI-compatible endpoints."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider base_url must be an absolute HTTP(S) URL.")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Non-local LLM endpoints must use HTTPS.")
        if not model.strip():
            raise ValueError("Provider model must not be empty.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Provider timeout must be a finite number greater than zero.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ProviderError(f"LLM provider returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Could not reach the LLM provider: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("LLM provider returned malformed response JSON.") from exc

        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("LLM provider response did not contain a chat completion.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("LLM provider returned an empty completion.")
        return content


def provider_from_environment() -> OpenAICompatibleProvider:
    base_url = os.environ.get(
        "AUTOPILOT_LLM_BASE_URL",
        "https://api.openai.com/v1",
    )
    model = os.environ.get("AUTOPILOT_LLM_MODEL", "gpt-4o-mini")
    api_key = os.environ.get("AUTOPILOT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    return OpenAICompatibleProvider(base_url, model, api_key)
