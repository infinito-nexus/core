from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from typing import ClassVar
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-jellyfin/files/provision_mcp_identity.py"

MCP_USER = "mcpreader"
USER_ID = "0e3f1c9a4b8d4f27a1c6d5e2b7a90f13"

ENV: dict[str, str] = {
    "JELLYFIN_BASE": "http://jellyfin:8096",
    "JELLYFIN_ADMIN_USER": "administrator",
    "JELLYFIN_ADMIN_PASSWORD": "a" * 32,
    "MCP_USER": MCP_USER,
    "MCP_PASSWORD": "b" * 32,
    "MCP_DEVICE_ID": "infinito-deploy",
}


def load(current_token: str = ""):
    spec = importlib.util.spec_from_file_location("provision_mcp_identity", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {**ENV, "MCP_CURRENT_TOKEN": current_token}):
        spec.loader.exec_module(module)
    return module


class ScriptedCalls:
    """Answers the module's ``call`` from a table of (method, path prefix) rules.

    Args:
        rules: ordered (method, path_prefix, answer) triples; the first match wins.
    """

    def __init__(self, rules):
        self.rules = rules
        self.seen: list[tuple[str, str]] = []

    def __call__(self, method, path, payload=None, token=None):
        self.seen.append((method, path))
        for rule_method, prefix, answer in self.rules:
            if method == rule_method and path.startswith(prefix):
                return answer
        raise AssertionError(f"unscripted call: {method} {path}")

    def paths(self, method: str) -> list[str]:
        return [path for seen_method, path in self.seen if seen_method == method]


AUTH = "/Users/AuthenticateByName"
TOKEN_OK = (200, {"AccessToken": "fresh-token"})


def run(module, calls) -> str:
    buffer = io.StringIO()
    with patch.object(module, "call", calls), redirect_stdout(buffer):
        module.main()
    return buffer.getvalue()


class TestIdempotenceProbe(unittest.TestCase):
    def test_a_live_stored_token_is_reused(self) -> None:
        module = load(current_token="stored-token")
        calls = ScriptedCalls(
            [("POST", AUTH, TOKEN_OK), ("GET", "/System/Info", (200, {}))]
        )
        self.assertEqual(run(module, calls), "UNCHANGED\nstored-token\n")

    def test_a_stale_stored_token_is_replaced(self) -> None:
        module = load(current_token="stale-token")
        calls = ScriptedCalls(
            [("POST", AUTH, TOKEN_OK), ("GET", "/System/Info", (401, "expired"))]
        )
        self.assertEqual(run(module, calls), "CHANGED\nfresh-token\n")

    def test_without_a_stored_token_the_fresh_one_is_printed(self) -> None:
        module = load()
        calls = ScriptedCalls([("POST", AUTH, TOKEN_OK)])
        self.assertEqual(run(module, calls), "CHANGED\nfresh-token\n")
        self.assertNotIn("/System/Info", calls.paths("GET"))


class TestPasswordConvergence(unittest.TestCase):
    EXISTING: ClassVar[list] = [{"Name": MCP_USER, "Id": USER_ID}]

    def _repair_rules(self, password_answer):
        """Rules for a run whose MCP password no longer authenticates."""
        answers = iter([(401, "invalid"), TOKEN_OK, TOKEN_OK])
        return [
            ("POST", AUTH, None),
            ("GET", "/Users", (200, self.EXISTING)),
            ("POST", f"/Users/{USER_ID}/Policy", (204, None)),
            ("POST", "/Users/Password", password_answer),
        ], answers

    def _run_repair(self, password_answer) -> tuple[str, ScriptedCalls]:
        module = load()
        rules, answers = self._repair_rules(password_answer)
        calls = ScriptedCalls(rules)

        def dispatch(method, path, payload=None, token=None):
            calls.seen.append((method, path))
            if method == "POST" and path.startswith(AUTH):
                return next(answers)
            for rule_method, prefix, answer in rules:
                if method == rule_method and path.startswith(prefix) and answer:
                    return answer
            raise AssertionError(f"unscripted call: {method} {path}")

        buffer = io.StringIO()
        with patch.object(module, "call", dispatch), redirect_stdout(buffer):
            module.main()
        return buffer.getvalue(), calls

    def test_a_drifted_password_is_converged_on_the_existing_user(self) -> None:
        output, calls = self._run_repair((204, None))
        self.assertIn("fresh-token", output)
        self.assertIn(f"/Users/Password?userId={USER_ID}", calls.paths("POST"))

    def test_a_repaired_password_is_reported_as_changed(self) -> None:
        output, _ = self._run_repair((204, None))
        self.assertEqual(output.splitlines()[0], "CHANGED")

    def test_a_200_answer_to_the_password_write_is_accepted(self) -> None:
        output, _ = self._run_repair((200, {}))
        self.assertIn("fresh-token", output)

    def test_a_rejected_password_write_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_repair((404, "no such user"))


if __name__ == "__main__":
    unittest.main()
