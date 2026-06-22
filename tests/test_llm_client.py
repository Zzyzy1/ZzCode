import json
import unittest
from unittest.mock import patch

from zzcode.llm.client import LLMResponse, ZzCodeLLM, normalize_chat_response


class LLMClientTest(unittest.TestCase):
    def test_normalize_chat_response_parses_tool_calls(self) -> None:
        response = normalize_chat_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "need tool",
                            "tool_calls": [
                                {
                                    "id": "call_read",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "README.md"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )

        self.assertIsInstance(response, LLMResponse)
        self.assertEqual(response.content, "need tool")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].id, "call_read")
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "README.md"})
        self.assertIsNone(response.tool_calls[0].parse_error)

    def test_normalize_chat_response_records_argument_parse_error(self) -> None:
        response = normalize_chat_response(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_bad",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{bad json"},
                                }
                            ]
                        }
                    }
                ]
            }
        )

        self.assertEqual(response.content, "")
        self.assertEqual(response.tool_calls[0].arguments, {})
        self.assertIn("JSON parse failed", response.tool_calls[0].parse_error)

    def test_normalize_chat_response_supports_legacy_function_call(self) -> None:
        response = normalize_chat_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "function_call": {"name": "list_files", "arguments": '{"path": "."}'},
                        }
                    }
                ]
            }
        )

        self.assertEqual(response.tool_calls[0].id, "call_0")
        self.assertEqual(response.tool_calls[0].name, "list_files")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "."})

    def test_chat_sends_tools_and_returns_standard_response(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path": "README.md"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

        client = ZzCodeLLM(model="model", api_key="key", base_url="https://example.test/v1", timeout=12)
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.chat([{"role": "user", "content": "read"}], tools=tools)

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["payload"]["tools"], tools)
        self.assertEqual(captured["payload"]["messages"], [{"role": "user", "content": "read"}])
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "README.md"})

    def test_think_still_returns_text_content(self) -> None:
        def fake_urlopen(request, timeout):
            return _FakeResponse({"choices": [{"message": {"content": "final answer"}}]})

        client = ZzCodeLLM(model="model", api_key="key", base_url="https://example.test/v1")
        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.think([{"role": "user", "content": "hello"}])

        self.assertEqual(response, "final answer")


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.body).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
