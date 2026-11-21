from __future__ import annotations

import importlib.util
import io
import json
import threading
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/svc-ai-litellm"
SPEC = importlib.util.spec_from_file_location(
    "validate_consumers", ROLE / "files/python/validate/consumers.py"
)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class Response(io.StringIO):
    status = 200


class TestValidateConsumers(unittest.TestCase):
    def setUp(self):
        self.key = "secret-consumer-key-not-for-output"
        self.payload = {
            "base_url": "http://127.0.0.1:4000",
            "timeout": 60,
            "workers": 3,
            "codex_reasoning_effort": "medium",
            "max_output_tokens": 512,
            "retry_policy": {"retries": 2, "delay": 60, "max_delay": 120},
            "consumers": [
                {"alias": "dsk-gnt-claude", "key": self.key},
                {"alias": "web-app-openwebui", "key": "other-consumer-key"},
            ],
            "models": ["lmstudio/qwen3-coder", "anthropic/claude-opus-5-5"],
        }

    def test_every_key_tests_every_model_through_both_native_apis(self):
        with patch.object(
            validation, "request_check", return_value={"ok": True}
        ) as request:
            result = validation.validate(self.payload)
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 10)
        for consumer in self.payload["consumers"]:
            calls = [
                call.args
                for call in request.call_args_list
                if call.args[1] == consumer["key"]
            ]
            self.assertEqual(len(calls), 5)
            self.assertEqual(calls[0][2:4], ("/v1/models", None))
            self.assertEqual(
                {(call[2], call[3]["model"]) for call in calls[1:]},
                {
                    (endpoint, model)
                    for endpoint in ("/v1/chat/completions", "/v1/messages")
                    for model in self.payload["models"]
                },
            )
        self.assertNotIn(self.key, json.dumps(result))

    def test_one_rejected_key_does_not_skip_other_consumers(self):
        def check(base, key, endpoint, body, timeout):
            return {
                "ok": key != self.key,
                "http_status": 401 if key == self.key else 200,
            }

        with patch.object(validation, "request_check", side_effect=check) as request:
            result = validation.validate(self.payload)
        self.assertFalse(result["ok"])
        self.assertEqual(request.call_count, 6)
        self.assertEqual(sum(check["ok"] for check in result["checks"]), 5)

    def test_missing_key_is_reported_without_an_http_request(self):
        self.payload["consumers"] = [{"alias": "dsk-gnt-claude", "key": ""}]
        with patch.object(validation, "request_check") as request:
            result = validation.validate(self.payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"][0]["reason"], "missing_consumer_key")
        request.assert_not_called()

    def test_codex_key_also_checks_the_responses_api_for_every_model(self):
        self.payload["consumers"] = [{"alias": "dsk-gnt-codex", "key": self.key}]
        with patch.object(
            validation, "request_check", return_value={"ok": True}
        ) as request:
            self.assertTrue(validation.validate(self.payload)["ok"])
        responses = [
            call.args
            for call in request.call_args_list
            if call.args[2] == "/v1/responses"
        ]
        self.assertEqual(len(responses), 2)
        self.assertEqual(
            {call[3]["model"] for call in responses}, set(self.payload["models"])
        )
        for call in responses:
            self.assertEqual(call[1], self.key)
            self.assertEqual(call[3]["max_output_tokens"], 512)
            self.assertEqual(call[3]["reasoning"], {"effort": "medium"})
            self.assertNotIn("messages", call[3])
            self.assertEqual(call[3]["input"], "Reply OK.")

    def test_responses_endpoint_requires_the_actual_response_shape(self):
        for data, valid in (
            (
                {
                    "object": "response",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "OK"}],
                        }
                    ],
                },
                True,
            ),
            ({"object": "response", "output": []}, False),
            ({"choices": [{}]}, False),
        ):
            with patch(
                "urllib.request.urlopen", return_value=Response(json.dumps(data))
            ):
                result = validation.request_check(
                    self.payload["base_url"], self.key, "/v1/responses", {}, 60
                )
                self.assertIs(result["ok"], valid)

    def test_anthropic_endpoint_failure_fails_the_validation(self):
        def check(base, key, endpoint, body, timeout):
            return {"ok": endpoint != "/v1/messages"}

        with patch.object(validation, "request_check", side_effect=check):
            self.assertFalse(validation.validate(self.payload)["ok"])

    def test_no_chat_models_still_validates_every_key_and_marks_inference_skipped(self):
        self.payload["models"] = []
        with patch.object(
            validation, "request_check", return_value={"ok": True}
        ) as request:
            result = validation.validate(self.payload)
        self.assertTrue(result["ok"])
        self.assertTrue(result["inference_skipped"])
        self.assertEqual(request.call_count, 2)

    def test_wire_request_uses_consumer_key_and_anthropic_protocol(self):
        seen = []

        def send(request, timeout):
            seen.append((request, timeout))
            return Response(
                '{"type":"message","content":[{"type":"text","text":"OK"}]}'
            )

        body = {
            "model": "lmstudio/qwen3-coder",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply OK."}],
        }
        with patch("urllib.request.urlopen", side_effect=send):
            result = validation.request_check(
                self.payload["base_url"], self.key, "/v1/messages", body, 60
            )
        self.assertTrue(result["ok"])
        request, timeout = seen[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4000/v1/messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + self.key)
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(timeout, 60)

    def test_http_200_with_wrong_response_shape_is_a_failure(self):
        for path in ("/v1/models", "/v1/messages", "/v1/chat/completions"):
            with (
                self.subTest(path=path),
                patch("urllib.request.urlopen", return_value=Response("{}")),
            ):
                result = validation.request_check(
                    self.payload["base_url"], self.key, path, None, 60
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["reason"], "invalid_response")

    def test_rejected_budget_is_diagnosed_without_leaking_key_or_raw_error(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/" + self.key,
            402,
            self.key,
            None,
            io.BytesIO(("Budget exceeded: " + self.key).encode()),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = validation.request_check(
                self.payload["base_url"], self.key, "/v1/messages", {}, 60
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 402)
        self.assertIn("budget", result["error_signals"])
        self.assertNotIn(self.key, json.dumps(result))

    def test_connection_error_is_sanitized(self):
        with patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError(self.key)
        ):
            result = validation.request_check(
                self.payload["base_url"], self.key, "/v1/models", None, 60
            )
        self.assertEqual(result, {"ok": False, "reason": "gateway_connection_failed"})

    def retry(self):
        return validation.request_with_retry(
            self.payload["base_url"],
            self.key,
            "/v1/messages",
            {},
            self.payload["timeout"],
            self.payload["retry_policy"],
        )

    def test_rate_limit_waits_for_retry_after_then_requires_a_successful_response(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/messages",
            429,
            self.key,
            {"Retry-After": "90"},
            io.BytesIO(("Rate limit " + self.key).encode()),
        )
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[
                    error,
                    Response(
                        '{"type":"message","content":[{"type":"text","text":"OK"}]}'
                    ),
                ],
            ) as request,
            patch.object(validation.time, "sleep") as sleep,
        ):
            result = self.retry()
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(90)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["retry_wait_seconds"], 90)
        self.assertNotIn(self.key, json.dumps(result))

    def test_adapter_wrapped_rate_limit_is_retried_without_retrying_other_server_errors(
        self,
    ):
        with (
            patch.object(
                validation,
                "request_check",
                side_effect=[
                    {"ok": False, "http_status": 500, "error_signals": ["rate limit"]},
                    {"ok": True, "http_status": 200},
                ],
            ),
            patch.object(validation.time, "sleep") as sleep,
        ):
            self.assertTrue(self.retry()["ok"])
        sleep.assert_called_once_with(60)

    def test_repeated_rate_limits_still_fail_after_the_bounded_retry_count(self):
        with (
            patch.object(
                validation,
                "request_check",
                return_value={"ok": False, "http_status": 429},
            ) as request,
            patch.object(validation.time, "sleep") as sleep,
        ):
            result = self.retry()
        self.assertFalse(result["ok"])
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(result["retry_wait_seconds"], 120)

    def test_only_the_lmstudio_engine_fetch_failure_400_is_retried(self):
        engine = (
            "litellm.BadRequestError: OpenAIException - Error code: 400 - "
            "{'error': 'Engine protocol predict request failed: fetch failed'} "
        )
        cases = (
            (400, engine, 2),
            (400, "litellm.BadRequestError: OpenAIException - fetch failed ", 1),
            (500, engine, 1),
            (400, engine + "Invalid API key ", 1),
        )
        for status, body, calls in cases:
            error = urllib.error.HTTPError(
                "http://127.0.0.1/v1/messages",
                status,
                self.key,
                None,
                io.BytesIO((body + self.key).encode()),
            )
            answer = Response(
                '{"type":"message","content":[{"type":"text","text":"OK"}]}'
            )
            with (
                self.subTest(status=status, body=body),
                patch("urllib.request.urlopen", side_effect=[error, answer]) as request,
                patch.object(validation.time, "sleep") as sleep,
            ):
                result = self.retry()
                self.assertEqual(request.call_count, calls)
                self.assertIs(result["ok"], calls == 2)
                self.assertEqual(sleep.call_count, calls - 1)
                self.assertNotIn(self.key, json.dumps(result))

    def test_permanent_errors_and_daily_quota_are_not_retried(self):
        errors = [
            {"ok": False, "http_status": status} for status in (401, 402, 403, 404, 500)
        ] + [
            {
                "ok": False,
                "http_status": 500,
                "error_signals": ["rate limit", "credit balance"],
            },
            {
                "ok": False,
                "http_status": 429,
                "reason": "provider_daily_quota_exhausted",
            },
        ]
        for error in errors:
            with (
                self.subTest(error=error),
                patch.object(
                    validation, "request_check", return_value=error
                ) as request,
                patch.object(validation.time, "sleep") as sleep,
            ):
                self.assertFalse(self.retry()["ok"])
                request.assert_called_once()
                sleep.assert_not_called()

    def test_daily_quota_message_is_reported_without_printing_the_raw_error(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/messages",
            429,
            self.key,
            None,
            io.BytesIO(
                ("Rate limit exceeded: free-models-per-day " + self.key).encode()
            ),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = validation.request_check(
                self.payload["base_url"], self.key, "/v1/messages", {}, 60
            )
        self.assertEqual(result["reason"], "provider_daily_quota_exhausted")
        self.assertNotIn(self.key, json.dumps(result))

    def test_retry_after_larger_than_the_wait_budget_fails_without_retrying_early(self):
        with (
            patch.object(
                validation,
                "request_check",
                return_value={
                    "ok": False,
                    "http_status": 429,
                    "retry_after_seconds": 3600,
                },
            ) as request,
            patch.object(validation.time, "sleep") as sleep,
        ):
            self.assertEqual(
                self.retry()["reason"], "retry_after_exceeds_validation_limit"
            )
            request.assert_called_once()
            sleep.assert_not_called()

    def test_retry_after_accepts_seconds_and_http_dates_and_ignores_invalid_values(
        self,
    ):
        with patch.object(validation.time, "time", return_value=0):
            self.assertEqual(
                validation.retry_after_seconds("Thu, 01 Jan 1970 00:01:30 GMT"), 90
            )
        self.assertEqual(validation.retry_after_seconds("60"), 60)
        for value in (None, "invalid", "nan", "inf"):
            self.assertIsNone(validation.retry_after_seconds(value))

    def test_invalid_retry_policy_fails_before_using_a_key(self):
        self.payload["retry_policy"]["retries"] = -1
        with patch.object(validation, "request_check") as request:
            with self.assertRaisesRegex(ValueError, "retry_policy.retries"):
                validation.validate(self.payload)
            request.assert_not_called()

    def test_wrapped_model_error_is_identified_without_printing_provider_payload(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/v1/messages",
            500,
            self.key,
            None,
            io.BytesIO(
                (
                    "litellm.NotFoundError: No endpoints available for openrouter/free "
                    + self.key
                ).encode()
            ),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = validation.request_check(
                self.payload["base_url"], self.key, "/v1/messages", {}, 60
            )
        self.assertFalse(result["ok"])
        self.assertIn("notfounderror", result["error_signals"])
        self.assertIn("no endpoints available", result["error_signals"])
        self.assertNotIn(self.key, json.dumps(result))

    def test_cli_failure_does_not_emit_its_input_or_exception(self):
        with (
            patch("sys.stdin", io.StringIO(self.key)),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(validation.main(), 1)
        self.assertFalse(json.loads(output.getvalue())["ok"])
        self.assertNotIn(self.key, output.getvalue())

    def test_task_masks_keys_and_reports_sanitized_failure_in_a_separate_assertion(
        self,
    ):
        tasks = load_yaml_any(ROLE / "tasks/utils/validate/consumers.yml")
        probe, assertion = tasks
        self.assertEqual(probe["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
        self.assertFalse(probe["failed_when"])
        self.assertNotIn("CONSUMER_KEYS", probe["ansible.builtin.shell"])
        self.assertIn("LITELLM_CONSUMER_KEYS", probe["args"]["stdin"])
        self.assertIn(
            "litellm_consumer_validation.rc == 0",
            assertion["ansible.builtin.assert"]["that"],
        )
        key_tasks = load_yaml_any(ROLE / "tasks/utils/prove_keys.yml")
        self.assertTrue(
            any(
                task.get("ansible.builtin.include_tasks")
                == "utils/validate/consumers.yml"
                for task in key_tasks
            )
        )

    def test_task_model_list_only_probes_served_chat_aliases_once(self):
        task = load_yaml_any(ROLE / "tasks/utils/validate/consumers.yml")[0]
        renderer = Environment(autoescape=False)  # noqa: S701 JSON payload, not HTML
        renderer.filters.update(FilterModule().filters())
        renderer.tests.update(TestModule().tests())
        rendered = renderer.from_string(task["args"]["stdin"]).render(
            LITELLM_CONSUMER_KEYS=self.payload["consumers"],
            LITELLM_OLLAMA_BACKEND=False,
            LITELLM_LMSTUDIO_BACKEND=True,
            LITELLM_SERVED_PROVIDERS=["anthropic", "mock"],
            LITELLM_REMOTE_MODELS=[
                {"provider": "anthropic", "alias": "cloud"},
                {"provider": "openrouter", "alias": "unserved"},
                {"provider": "mock", "alias": "mock"},
            ],
            LITELLM_PORT=4000,
            LITELLM_UPSTREAM_TIMEOUT=60,
            lookup=lambda *args: (
                self.payload["codex_reasoning_effort"]
                if args[-1].endswith("reasoning_effort")
                else self.payload[args[-1].rsplit(".", 1)[-1]]
                if ".validation." in args[-1]
                else self.payload["retry_policy"][args[-1].rsplit(".", 1)[-1]]
                if "consumer_validation" in args[-1]
                else [
                    {"alias": "local"},
                    {"alias": "local"},
                    {"alias": "embed-small"},
                ]
            ),
        )
        payload = json.loads(rendered)
        self.assertEqual(payload["models"], ["local", "cloud", "mock"])
        self.assertEqual(payload["consumers"], self.payload["consumers"])
        self.assertEqual(payload["base_url"], "http://127.0.0.1:4000")
        self.assertEqual(payload["retry_policy"], self.payload["retry_policy"])

    def test_inference_requests_overlap_with_a_bounded_worker_count(self):
        self.payload["consumers"] = self.payload["consumers"][:1]
        self.payload["models"] = self.payload["models"][:1]
        self.payload["workers"] = 2
        barrier = threading.Barrier(2)
        seen = set()

        def check(base, key, endpoint, body, timeout):
            if body is not None:
                seen.add(threading.get_ident())
                barrier.wait(timeout=3)
            return {"ok": True}

        with patch.object(validation, "request_check", side_effect=check):
            self.assertTrue(validation.validate(self.payload)["ok"])
        self.assertEqual(len(seen), 2)

    def test_empty_or_error_responses_fail_on_every_inference_protocol(self):
        fixtures = {
            "/v1/chat/completions": {"choices": [{"message": {"content": " "}}]},
            "/v1/messages": {
                "type": "message",
                "content": [{"type": "thinking", "thinking": "OK"}],
            },
            "/v1/responses": {"object": "response", "output": []},
        }
        for path, data in fixtures.items():
            with (
                self.subTest(path=path),
                patch(
                    "urllib.request.urlopen", return_value=Response(json.dumps(data))
                ),
            ):
                self.assertFalse(
                    validation.request_check(
                        self.payload["base_url"], self.key, path, {}, 60
                    )["ok"]
                )

    def test_answer_text_is_required_even_when_the_envelope_is_valid(self):
        fixtures = {
            "/v1/chat/completions": {"choices": [{"message": {"content": "OK"}}]},
            "/v1/messages": {
                "type": "message",
                "content": [{"type": "text", "text": "OK"}],
            },
            "/v1/responses": {
                "object": "response",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ],
            },
        }
        for path, data in fixtures.items():
            for error, expected in ((None, True), ({"code": "provider_error"}, False)):
                with (
                    self.subTest(path=path, error=error),
                    patch(
                        "urllib.request.urlopen",
                        return_value=Response(json.dumps(dict(data, error=error))),
                    ),
                ):
                    self.assertIs(
                        validation.request_check(
                            self.payload["base_url"], self.key, path, {}, 60
                        )["ok"],
                        expected,
                    )

    def test_parallel_failure_is_reported_and_other_jobs_are_checked(self):
        def check(base, key, endpoint, body, timeout):
            return {"ok": body is None or body["model"] != self.payload["models"][0]}

        with patch.object(validation, "request_check", side_effect=check) as request:
            result = validation.validate(self.payload)
        self.assertFalse(result["ok"])
        self.assertEqual(request.call_count, 10)

    def test_parallel_configuration_is_required_and_positive(self):
        for name in ("workers", "max_output_tokens"):
            for value in (0, -1, True):
                with (
                    self.subTest(name=name, value=value),
                    patch.object(validation, "request_check") as request,
                ):
                    payload = dict(self.payload, **{name: value})
                    with self.assertRaises(ValueError):
                        validation.validate(payload)
                    request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
