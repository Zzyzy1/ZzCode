"""OpenAI-compatible LLM client used by the text ReAct demo."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class ThinkClient(Protocol):
    """Minimal protocol required by the text ReAct agent."""

    def think(self, messages: list[dict[str, str]], temperature: float = 0) -> str | None:
        """Return model text for the given chat messages."""


class ZzCodeLLM:
    """Small OpenAI-compatible client inspired by hello-agents chapter 4."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        stream: bool = False,
    ) -> None:
        load_env_file()

        self.model = model or os.getenv("LLM_MODEL_ID") or os.getenv("ZZCODE_MODEL")
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("ZZCODE_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("ZZCODE_BASE_URL")
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT") or os.getenv("ZZCODE_TIMEOUT") or 60)
        self.stream = stream

        if not all([self.model, self.api_key, self.base_url]):
            raise ValueError(
                "LLM_MODEL_ID/LLM_API_KEY/LLM_BASE_URL or "
                "ZZCODE_MODEL/ZZCODE_API_KEY/ZZCODE_BASE_URL must be configured."
            )

    def think(self, messages: list[dict[str, str]], temperature: float = 0) -> str | None:
        """Call the model and return its full text response."""

        print(f"Calling model: {self.model}")
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            request = urllib.request.Request(
                url=self._chat_completions_url(),
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"].get("content") or ""
            print(content)
            return content
        except urllib.error.HTTPError as exc:  # pragma: no cover - depends on remote provider
            error_body = exc.read().decode("utf-8", errors="replace")
            print(f"LLM HTTP error {exc.code}: {error_body}")
            return None
        except Exception as exc:  # pragma: no cover - depends on remote provider
            print(f"LLM call failed: {exc}")
            return None

    def _chat_completions_url(self) -> str:
        base = str(self.base_url).rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    """Load simple KEY=VALUE pairs without requiring python-dotenv."""

    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
