"""Unit tests for the bearer authentication of the reusable MCP adapter."""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python/auth.py"

spec = importlib.util.spec_from_file_location("adapter_auth", MODULE_PATH)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


class TestAuthorizeClient(unittest.TestCase):
    def test_the_issued_bearer_is_accepted(self):
        self.assertIsNone(auth.authorize_client("s3cret", "Bearer s3cret"))

    def test_a_wrong_bearer_is_refused(self):
        with self.assertRaises(PermissionError):
            auth.authorize_client("s3cret", "Bearer other")

    def test_a_missing_header_is_refused(self):
        with self.assertRaises(PermissionError):
            auth.authorize_client("s3cret", "")

    def test_an_unset_bearer_refuses_everyone(self):
        with self.assertRaises(PermissionError):
            auth.authorize_client("", "Bearer anything")

    def test_the_bearer_is_compared_in_constant_time(self):
        with mock.patch.object(
            auth.hmac, "compare_digest", wraps=auth.hmac.compare_digest
        ) as compare:
            auth.authorize_client("s3cret", "Bearer s3cret")
            with self.assertRaises(PermissionError):
                auth.authorize_client("s3cret", "Bearer s3creT")
        self.assertEqual(
            compare.call_args_list,
            [mock.call(b"s3cret", b"s3cret"), mock.call(b"s3creT", b"s3cret")],
        )

    def test_a_non_ascii_bearer_is_refused_not_raised(self):
        with self.assertRaises(PermissionError):
            auth.authorize_client("s3cret", "Bearer s3crét")


AGENT_TOKENS = {"mant0a": "token-of-mant", "impl0a": "token-of-impl"}


class TestAuthorizeAgent(unittest.TestCase):
    def test_an_agent_presenting_its_own_token_is_accepted(self):
        for agent, token in AGENT_TOKENS.items():
            with self.subTest(agent=agent):
                self.assertIsNone(
                    auth.authorize_agent(AGENT_TOKENS, agent, f"Bearer {token}")
                )

    def test_a_token_of_one_agent_is_refused_for_another(self):
        with self.assertRaises(PermissionError) as error:
            auth.authorize_agent(AGENT_TOKENS, "impl0a", "Bearer token-of-mant")
        self.assertEqual(str(error.exception), auth.DENY_UNAUTHENTICATED)

    def test_an_agent_without_a_token_is_refused(self):
        with self.assertRaises(PermissionError):
            auth.authorize_agent(AGENT_TOKENS, "ghost0a", "Bearer token-of-mant")

    def test_the_agent_token_is_compared_in_constant_time(self):
        with (
            mock.patch.object(
                auth.hmac, "compare_digest", wraps=auth.hmac.compare_digest
            ) as compare,
            self.assertRaises(PermissionError),
        ):
            auth.authorize_agent(AGENT_TOKENS, "impl0a", "Bearer token-of-mant")
        self.assertEqual(
            compare.call_args_list,
            [mock.call(b"token-of-mant", b"token-of-impl")],
        )


if __name__ == "__main__":
    unittest.main()
