from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/svc-ai-litellm"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"  # nocheck: url


def flatten(tasks):
    for task in tasks:
        yield task
        yield from flatten(task.get("block", []))


SPEC = importlib.util.spec_from_file_location(
    "validate_provider", ROLE / "files/python/validate/provider.py"
)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class ProviderError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status_code = status


class TestValidateProvider(unittest.TestCase):
    def setUp(self):
        self.declaration = {
            "provider": "anthropic",
            "alias": "anthropic/claude-opus-5-5",
            "model": "anthropic/claude-opus-5-5",
        }
        self.key = "secret-regression-key-not-for-output"
        self.completion = Mock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
            )
        )
        self.environment = patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": self.key, "LITELLM_VALIDATION_OUTPUT_TOKENS": "512"},
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.sdk = patch.dict(
            sys.modules, {"litellm": SimpleNamespace(completion=self.completion)}
        )
        self.sdk.start()
        self.addCleanup(self.sdk.stop)

    def test_uses_the_deployed_key_and_exact_model_without_router_fallback(self):
        result = validation.validate(self.declaration, 60)
        self.assertTrue(result["ok"])
        self.completion.assert_called_once_with(
            model=self.declaration["model"],
            api_key=self.key,
            messages=[{"role": "user", "content": "Reply OK."}],
            max_tokens=512,
            timeout=60,
            num_retries=0,
            max_retries=0,
        )
        self.assertNotIn(self.key, json.dumps(result))

    def test_missing_deployed_key_fails_without_requesting_a_model(self):
        with patch.dict("os.environ", {}, clear=True):
            result = validation.validate(self.declaration, 60)
        self.assertFalse(result["ok"])
        self.assertIn("ANTHROPIC_API_KEY", result["reason"])
        self.completion.assert_not_called()

    def test_openrouter_reads_its_own_key(self):
        declaration = {
            "provider": "openrouter",
            "alias": "openrouter/free",
            "model": "openrouter/openrouter/free",
        }
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "router-key",
                "LITELLM_VALIDATION_OUTPUT_TOKENS": "512",
            },
            clear=True,
        ):
            self.assertTrue(validation.validate(declaration, 60)["ok"])
        self.assertEqual(self.completion.call_args.kwargs["api_key"], "router-key")
        self.assertEqual(
            self.completion.call_args.kwargs["model"], declaration["model"]
        )

    def test_openai_transport_uses_the_explicit_openrouter_endpoint_and_key(self):
        declaration = {
            "provider": "openrouter",
            "alias": "openrouter/free",
            "model": "openai/openrouter/free",
            "api_base": OPENROUTER_BASE,
        }
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "router-key",
                "LITELLM_VALIDATION_OUTPUT_TOKENS": "512",
            },
            clear=True,
        ):
            self.assertTrue(validation.validate(declaration, 60)["ok"])
        self.assertEqual(self.completion.call_args.kwargs["api_key"], "router-key")
        self.assertEqual(self.completion.call_args.kwargs["api_base"], OPENROUTER_BASE)
        self.assertEqual(
            self.completion.call_args.kwargs["model"], "openai/openrouter/free"
        )

    def test_task_passes_the_same_explicit_endpoint_to_the_provider_probe(self):
        task = load_yaml_any(ROLE / "tasks/utils/validate/providers.yml")[1]
        renderer = Environment(autoescape=False)  # noqa: S701 JSON payload, not HTML
        renderer.filters.update(FilterModule().filters())
        for base in (None, OPENROUTER_BASE):
            with self.subTest(base=base):
                declaration = dict(self.declaration)
                if base is not None:
                    declaration["api_base"] = base
                result = json.loads(
                    renderer.from_string(task["args"]["stdin"]).render(
                        LITELLM_REMOTE_MODELS=[declaration],
                        LITELLM_KEYED_PROVIDERS=["anthropic"],
                        application_id="svc-ai-litellm",
                        lookup=lambda *args: (
                            3 if args[-1].endswith("workers") else "fixture worker"
                        ),
                    )
                )
                self.assertEqual(result["models"], [declaration])
                self.assertEqual(result["workers"], 3)

    def test_provider_errors_fail_with_actionable_sanitized_diagnostics(self):
        for status, expected in (
            (401, "invalid_key"),
            (402, "insufficient_credit"),
            (403, "access_denied"),
            (404, "model_unavailable"),
            (429, "rate_limited"),
            (503, "provider_unavailable"),
            (400, "provider_request_failed"),
        ):
            with self.subTest(status=status):
                self.completion.side_effect = ProviderError(status, self.key)
                result = validation.validate(self.declaration, 60)
                self.assertFalse(result["ok"])
                self.assertEqual(result["http_status"], status)
                self.assertIn(expected, result["reason"])
                self.assertNotIn(self.key, json.dumps(result))

    def test_anthropic_credit_error_is_identified_even_with_http_400(self):
        self.completion.side_effect = ProviderError(
            400, "Credit balance is too low: " + self.key
        )
        result = validation.validate(self.declaration, 60)
        self.assertIn("insufficient_credit", result["reason"])
        self.assertNotIn(self.key, json.dumps(result))

    def test_sdk_prints_and_logs_cannot_expose_credentials(self):
        def fail_with_noisy_output(**kwargs):
            print(kwargs["api_key"])
            print(kwargs["api_key"], file=sys.stderr)
            logging.getLogger("provider-sdk-test").error(kwargs["api_key"])
            raise ProviderError(401, kwargs["api_key"])

        self.completion.side_effect = fail_with_noisy_output
        previous_logging = logging.root.manager.disable
        with (
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()) as errors,
        ):
            result = validation.validate(self.declaration, 60)
        self.assertFalse(result["ok"])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(logging.root.manager.disable, previous_logging)

    def test_connectivity_failure_does_not_print_the_exception(self):
        self.completion.side_effect = ConnectionError(self.key)
        result = validation.validate(self.declaration, 60)
        self.assertFalse(result["ok"])
        self.assertIn("connectivity", result["reason"])
        self.assertNotIn(self.key, json.dumps(result))

    def test_cli_returns_failure_and_prints_only_the_sanitized_result(self):
        self.completion.side_effect = ProviderError(401, self.key)
        with (
            patch.dict("os.environ", {"LITELLM_TIMEOUT": "60"}),
            patch("sys.stdin", io.StringIO(json.dumps(self.declaration))),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(validation.main(), 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertNotIn(self.key, output.getvalue())

    def test_setup_validates_even_without_consumer_keys_and_excludes_unserved_models(
        self,
    ):
        core = list(flatten(load_yaml_any(ROLE / "tasks/00_core.yml")))
        include = next(
            task
            for task in core
            if task.get("ansible.builtin.include_tasks")
            == "utils/validate/providers.yml"
        )
        self.assertFalse(
            any("CONSUMER_KEYS" in condition for condition in include["when"])
        )
        provision = next(
            index
            for index, task in enumerate(core)
            if task.get("ansible.builtin.include_tasks") == "01_keys.yml"
        )
        self.assertLess(core.index(include), provision)
        tasks = load_yaml_any(ROLE / "tasks/utils/validate/providers.yml")
        task = tasks[1]
        renderer = Environment(autoescape=False)  # noqa: S701 JSON payload, not HTML
        renderer.filters.update(FilterModule().filters())
        rendered = json.loads(
            renderer.from_string(task["args"]["stdin"]).render(
                application_id="svc-ai-litellm",
                lookup=lambda *args: (
                    3 if args[-1].endswith("workers") else "fixture worker"
                ),
                LITELLM_KEYED_PROVIDERS=["anthropic"],
                LITELLM_REMOTE_MODELS=[
                    self.declaration,
                    {"provider": "openrouter"},
                    {"provider": "mock"},
                ],
            )
        )
        self.assertEqual(rendered["models"], [self.declaration])
        self.assertFalse(task["changed_when"])
        self.assertNotIn("retries", task)
        self.assertEqual(task["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
        self.assertIn(
            "litellm_provider_validation.rc == 0",
            tasks[2]["ansible.builtin.assert"]["that"],
        )

    def test_provider_must_return_text_instead_of_only_reasoning(self):
        for content in (None, "", " "):
            self.completion.return_value.choices[0].message.content = content
            result = validation.validate(self.declaration, 60)
            self.assertFalse(result["ok"])
            self.assertIn("empty_response", result["reason"])

    def test_batch_workers_overlap_and_keep_failures(self):
        barrier = threading.Barrier(2)
        seen = set()

        def run(argv, **kwargs):
            seen.add(threading.get_ident())
            barrier.wait(timeout=3)
            declaration = json.loads(kwargs["input"])
            ok = declaration["alias"] == "first"
            return subprocess.CompletedProcess(
                argv, 0 if ok else 1, json.dumps({"ok": ok}), ""
            )

        payload = {
            "workers": 2,
            "worker_source": "fixture",
            "models": [
                dict(self.declaration, alias="first"),
                dict(self.declaration, alias="second"),
            ],
        }
        with patch.object(validation.subprocess, "run", side_effect=run):
            result = validation.validate_all(payload, 60)
        self.assertEqual(len(seen), 2)
        self.assertFalse(result["ok"])
        self.assertEqual([c["ok"] for c in result["checks"]], [True, False])
        self.assertNotIn(self.key, json.dumps(result))

    def test_crashed_or_noisy_worker_fails_without_exposing_its_output(self):
        payload = {
            "workers": 1,
            "worker_source": "fixture",
            "models": [self.declaration],
        }
        with patch.object(
            validation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, self.key, self.key),
        ):
            result = validation.validate_all(payload, 60)
        self.assertFalse(result["ok"])
        self.assertNotIn(self.key, json.dumps(result))

    def test_real_worker_process_executes_sdk_probe_in_isolation(self):
        payload = {
            "workers": 2,
            "models": [self.declaration, dict(self.declaration, alias="second")],
            "worker_source": read_text(
                str(ROLE / "files/python/validate/provider.py")
            ).replace(
                "from __future__ import annotations",
                'from __future__ import annotations\nimport sys,types\nsys.modules["litellm"] = types.SimpleNamespace(completion=lambda **kw: types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK"))]))',
            ),
        }
        with patch.dict(os.environ, {"LITELLM_TIMEOUT": "60"}):
            result = validation.validate_all(payload, 60)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["checks"]), 2)


if __name__ == "__main__":
    unittest.main()
