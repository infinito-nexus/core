import importlib.util
import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

SCRIPT = PROJECT_ROOT / "roles/sys-ctl-hlth-container/files/python/redact.py"
RULES_FILE = PROJECT_ROOT / "group_vars/all/22_logging.yml"

_SPEC = importlib.util.spec_from_file_location("hlth_container_redact", SCRIPT)
redact_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(redact_module)

PYTHON_ONLY_SYNTAX = re.compile(r"\(\?<?[=!]|\\[1-9]|\(\?P=")


def shared_document() -> dict:
    data = load_yaml_any(str(RULES_FILE))
    return {
        "replacement": data["LOG_REDACTION_REPLACEMENT"],
        "rules": data["LOG_REDACTION_RULES"],
    }


class TestSharedRedactionRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = shared_document()
        cls.replacement, cls.rules = redact_module.load_rules(cls.document)

    def assert_hidden(self, line: str, secret: str) -> None:
        result = redact_module.redact(line, self.replacement, self.rules)
        self.assertNotIn(secret, result)
        self.assertIn(self.replacement, result)

    def test_every_rule_compiles_with_exactly_one_capture_group(self) -> None:
        self.assertEqual(len(self.rules), len(self.document["rules"]))

    def test_every_rule_stays_inside_the_re2_subset_alloy_runs(self) -> None:
        offenders = [
            rule["name"]
            for rule in self.document["rules"]
            if PYTHON_ONLY_SYNTAX.search(rule["pattern"]) or "`" in rule["pattern"]
        ]
        self.assertEqual([], offenders)

    def test_rule_names_are_unique(self) -> None:
        names = [rule["name"] for rule in self.document["rules"]]
        self.assertEqual(len(names), len(set(names)))

    def test_a_key_value_password_is_hidden(self) -> None:
        self.assert_hidden(
            "login failed password=Synth3tic-Canary-Pass for biber",
            "Synth3tic-Canary-Pass",
        )

    def test_a_json_secret_is_hidden(self) -> None:
        self.assert_hidden(
            '{"client_secret": "canary-client-secret-value", "user": "biber"}',
            "canary-client-secret-value",
        )

    def test_an_authorization_header_is_hidden(self) -> None:
        self.assert_hidden(
            "Authorization: Basic Y2FuYXJ5OmNhbmFyeS1wYXNz",
            "Y2FuYXJ5OmNhbmFyeS1wYXNz",
        )

    def test_a_bearer_token_is_hidden(self) -> None:
        self.assert_hidden(
            "upstream call with bearer canaryBearerToken0123456789",
            "canaryBearerToken0123456789",
        )

    def test_a_url_password_is_hidden(self) -> None:
        self.assert_hidden(
            "connecting to postgres://app:canaryDbPass42@db:5432/app",
            "canaryDbPass42",
        )

    def test_a_json_web_token_is_hidden(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hcnkifQ.c2lnbmF0dXJlLWNhbmFyeQ"
        self.assert_hidden(f"session {token} accepted", token)

    def test_an_oauth_code_in_a_query_string_is_hidden(self) -> None:
        self.assert_hidden(
            '"GET /login/generic_oauth?state=abc&code=canaryAuthCode77 HTTP/1.1" 302',
            "canaryAuthCode77",
        )

    def test_an_aws_access_key_id_is_hidden(self) -> None:
        self.assert_hidden("using key AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE")

    def test_every_secret_of_a_canary_line_is_hidden(self) -> None:
        line = (
            "INFINITO-CANARY password=Canary-Pass-1 token=Canary-Token-2 "
            "Authorization: Bearer Canary-Bearer-3abcdef"
        )
        result = redact_module.redact(line, self.replacement, self.rules)
        for secret in ("Canary-Pass-1", "Canary-Token-2", "Canary-Bearer-3abcdef"):
            self.assertNotIn(secret, result)
        self.assertIn("INFINITO-CANARY", result)

    def test_a_line_without_secrets_is_left_unchanged(self) -> None:
        line = '10.0.0.1 - - "GET /index.html HTTP/1.1" 200 512 user biber logged in'
        self.assertEqual(line, redact_module.redact(line, self.replacement, self.rules))

    def test_the_text_around_a_secret_survives(self) -> None:
        result = redact_module.redact(
            "password=Canary-Pass-1 for biber", self.replacement, self.rules
        )
        self.assertEqual(f"password={self.replacement} for biber", result)


class TestRuleLoading(unittest.TestCase):
    def test_a_pattern_without_a_capture_group_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            redact_module.load_rules(
                {"replacement": "x", "rules": [{"name": "bad", "pattern": "secret"}]}
            )

    def test_a_pattern_with_two_capture_groups_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            redact_module.load_rules(
                {
                    "replacement": "x",
                    "rules": [{"name": "bad", "pattern": "(a)=(b)"}],
                }
            )

    def test_a_document_without_replacement_fails_loudly(self) -> None:
        with self.assertRaises(KeyError):
            redact_module.load_rules({"rules": []})


if __name__ == "__main__":
    unittest.main()
