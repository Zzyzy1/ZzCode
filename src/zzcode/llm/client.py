"""OpenAI-compatible LLM client used by the text ReAct demo."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class ThinkClient(Protocol):
    """文本 ReAct Agent 依赖的最小模型协议。"""

    def think(self, messages: list[dict[str, str]], temperature: float = 0) -> str | None:
        """请求模型生成文本。

        messages 是 OpenAI-compatible 消息列表；temperature 控制随机性；
        返回模型文本，失败时返回 None。
        """


class ZzCodeLLM:
    """OpenAI-compatible LLM 客户端。

    从参数或环境变量读取模型配置；think() 返回模型完整文本。
    """

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
        """调用 Chat Completions 接口。

        messages 是模型上下文；temperature 传给模型服务；
        返回 assistant 文本，HTTP 或网络失败时返回 None。
        """

        print(f"Calling model: {self.model}", file=sys.stderr)
        try:
            # 这里直接使用标准库 HTTP，避免第一阶段依赖 openai SDK。
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
            print(content, file=sys.stderr)
            return content
        except urllib.error.HTTPError as exc:  # pragma: no cover - depends on remote provider
            error_body = exc.read().decode("utf-8", errors="replace")
            print(f"LLM HTTP error {exc.code}: {error_body}", file=sys.stderr)
            return None
        except Exception as exc:  # pragma: no cover - depends on remote provider
            print(f"LLM call failed: {exc}", file=sys.stderr)
            return None

    def _chat_completions_url(self) -> str:
        """拼出 Chat Completions 请求地址。

        base_url 可以是服务根地址或完整 /chat/completions 地址；返回最终 URL。
        """

        base = str(self.base_url).rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    """读取简单 .env 文件。

    path 是 env 文件路径；函数只写入尚未存在的环境变量，不返回值。
    """

    env_path = Path(path)
    if not env_path.exists():
        return

    # 只支持 KEY=VALUE 子集，够第一阶段使用，也避免引入 python-dotenv。
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
