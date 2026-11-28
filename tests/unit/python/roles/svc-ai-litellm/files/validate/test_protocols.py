import importlib.util
import io
import json
import threading
import unittest
import urllib.error
from unittest.mock import patch

from . import PROJECT_ROOT

SPEC = importlib.util.spec_from_file_location(
    "validate_protocols",
    PROJECT_ROOT / "roles/svc-ai-litellm/files/python/validate/protocols.py",
)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)
PATHS = ("/v1/chat/completions", "/v1/messages", "/v1/responses")


class TestProtocols(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "model": "freellmapi/auto",
            "base_url": "http://gateway:4000",
            "timeout": 10,
            "workers": 3,
            "max_output_tokens": 512,
            "reasoning_effort": "medium",
        }
        self.key = "secret-regression-key"

    def test_stream_requires_text_and_protocol_completion(self):
        cases = (
            [{"choices": [{"delta": {"content": "OK"}}]}, "[DONE]"],
            [
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "OK"},
                },
                {"type": "message_stop"},
            ],
            [
                {"type": "response.output_text.delta", "delta": "OK"},
                {"type": "response.completed"},
            ],
        )
        for path, events in zip(PATHS, cases, strict=True):
            for selected, ok in (
                (events, True),
                (events[:1], False),
                (events[1:], False),
                ([{"type": "error", "error": self.key}], False),
            ):
                with self.subTest(path=path, events=selected):
                    source = "".join(
                        "data: " + (e if isinstance(e, str) else json.dumps(e)) + "\n\n"
                        for e in selected
                    )
                    with patch.object(
                        validation, "request", return_value=io.BytesIO(source.encode())
                    ):
                        result = validation.probe(
                            self.payload, self.key, (path, "stream")
                        )
                    self.assertEqual(result["ok"], ok)
                    self.assertNotIn(self.key, json.dumps(result))

    def test_tool_result_round_trip_for_each_protocol(self):
        first = (
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "infinito_probe",
                                        "arguments": '{"value":"OK"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "infinito_probe",
                        "input": {"value": "OK"},
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "infinito_probe",
                        "arguments": '{"value":"OK"}',
                    }
                ]
            },
        )
        final = (
            {"choices": [{"message": {"content": "OK"}}]},
            {"content": [{"type": "text", "text": "OK"}]},
            {
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ],
            },
        )

        def responder(expected, call, answer, bodies):
            def respond(payload, key, endpoint, body):
                self.assertEqual(key, self.key)
                self.assertEqual(endpoint, expected)
                bodies.append(json.loads(json.dumps(body)))
                return io.BytesIO(
                    json.dumps(call if len(bodies) == 1 else answer).encode()
                )

            return respond

        for path, call, answer in zip(PATHS, first, final, strict=True):
            bodies = []
            with (
                self.subTest(path=path),
                patch.object(
                    validation,
                    "request",
                    side_effect=responder(path, call, answer, bodies),
                ),
            ):
                self.assertTrue(
                    validation.probe(self.payload, self.key, (path, "tools"))["ok"]
                )
            self.assertEqual(len(bodies), 2)
            self.assertIn("tool_choice", bodies[0])
            self.assertNotIn("tool_choice", bodies[1])
            history = bodies[1]["input" if path.endswith("responses") else "messages"]
            self.assertIn("call-1", json.dumps(history[-1]))
            self.assertIn("OK", json.dumps(history[-1]))

    def test_invalid_tool_call_and_http_errors_fail_without_raw_details(self):
        for error in (
            urllib.error.HTTPError("http://gateway", 401, self.key, {}, io.BytesIO()),
            ValueError(self.key),
        ):
            with patch.object(validation, "request", side_effect=error):
                result = validation.probe(self.payload, self.key, (PATHS[0], "tools"))
            self.assertFalse(result["ok"])
            self.assertNotIn(self.key, json.dumps(result))
        with patch.object(
            validation, "request", return_value=io.BytesIO(b'{"choices":[]}')
        ):
            self.assertFalse(
                validation.probe(self.payload, self.key, (PATHS[0], "tools"))["ok"]
            )

    def test_responses_rejects_chat_objects_with_an_output_field(self):
        data = {
            "object": "chat.completion",
            "output": [{"type": "message", "content": [{"text": "OK"}]}],
        }
        self.assertFalse(validation.text_present(data, "/v1/responses"))

    def test_parallel_jobs_keep_every_protocol_failure(self):
        barrier = threading.Barrier(3)
        threads = set()

        def probe(payload, key, job):
            threads.add(threading.get_ident())
            barrier.wait(timeout=3)
            return {
                "endpoint": job[0],
                "operation": job[1],
                "ok": job != (PATHS[2], "tools"),
            }

        with patch.object(validation, "probe", side_effect=probe):
            result = validation.validate(self.payload, self.key)
        self.assertEqual(len(threads), 3)
        self.assertEqual(len(result["checks"]), 6)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
