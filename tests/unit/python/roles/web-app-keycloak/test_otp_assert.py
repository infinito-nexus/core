import copy
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template
from jinja2 import Environment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

ROLE = Path(PROJECT_ROOT) / "roles" / "web-app-keycloak"
INIT = ROLE / "tasks" / "02_init.yml"
POLICY_ASSERT = (
    "✅ Assert the OTP policy of '{{ application_id }}' is one Keycloak supports"
)
ENFORCED_ASSERT = (
    "✅ Assert '{{ application_id }}' enforces TOTP only where it offers it"
)
ROLE_VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
POLICY = SERVICES["keycloak"]["realm"]["otp_policy"]
OTP_VARIABLE_TESTS = {
    "KEYCLOAK_REALM_TOTP_ENABLED": "boolean",
    "KEYCLOAK_REALM_TOTP_ENFORCED": "boolean",
    "KEYCLOAK_REALM_OTP_POLICY_DIGITS": "integer",
    "KEYCLOAK_REALM_OTP_POLICY_PERIOD": "integer",
    "KEYCLOAK_REALM_OTP_POLICY_LOOK_AHEAD_WINDOW": "integer",
    "KEYCLOAK_REALM_OTP_POLICY_INITIAL_COUNTER": "integer",
    "KEYCLOAK_REALM_OTP_POLICY_CODE_REUSABLE": "boolean",
}
LISTS = {
    name: ROLE_VARS[name]
    for name in (
        "KEYCLOAK_REALM_OTP_POLICY_TYPES",
        "KEYCLOAK_REALM_OTP_POLICY_ALGORITHMS",
        "KEYCLOAK_REALM_OTP_POLICY_DIGIT_COUNTS",
    )
}


def _task(name: str) -> dict:
    return next(t for t in load_yaml_any(str(INIT)) if t.get("name") == name)[
        "ansible.builtin.assert"
    ]


def _policy(overrides: dict) -> dict:
    """Return the assert inputs of the shipped OTP policy with *overrides* applied.

    Args:
        overrides: values replacing those of ``otp_policy``, keyed by its key names.
    """
    return {
        **LISTS,
        **{
            f"KEYCLOAK_REALM_OTP_POLICY_{key.upper()}": value
            for key, value in {**POLICY, **overrides}.items()
        },
    }


def _holds(name: str, variables: dict) -> bool:
    """Whether every condition of the assert *name* holds, evaluated in order like Ansible.

    Args:
        name: the task name in ``tasks/02_init.yml``.
        variables: the variables the conditions read.
    """
    env = Environment(autoescape=True)
    env.filters["bool"] = bool
    that = _task(name)["that"]
    return all(
        bool(env.compile_expression(condition)(**variables))
        for condition in ([that] if isinstance(that, str) else that)
    )


class TestOtpPolicyAssert(unittest.TestCase):
    def test_the_shipped_policy_and_other_supported_values_pass(self) -> None:
        for overrides in (
            {},
            {"type": "hotp", "algorithm": "HmacSHA512", "digits": 8},
            {"period": 60, "look_ahead_window": 0, "initial_counter": 5},
        ):
            with self.subTest(overrides=overrides):
                self.assertTrue(_holds(POLICY_ASSERT, _policy(overrides)))

    def test_unsupported_or_mistyped_values_are_refused(self) -> None:
        refused = {
            "type": ("TOTP", "sha1", ""),
            "algorithm": ("SHA1", "HmacMD5"),
            "digits": (7, 0, "6", "eight", True, 6.0),
            "period": (0, -30, "30", "30s", 30.5, True),
            "look_ahead_window": (-1, "1", 1.5, False),
            "initial_counter": (-1, "0", 0.5),
        }
        for key, values in refused.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertFalse(_holds(POLICY_ASSERT, _policy({key: value})))

    def test_the_message_names_the_raw_value_the_operator_set(self) -> None:
        message = (
            Environment(autoescape=True)
            .from_string(_task(POLICY_ASSERT)["fail_msg"])
            .render(**_policy({"period": "30s", "digits": "eight"}))
        )
        self.assertIn("services.keycloak.realm.otp_policy", message)
        self.assertIn("period '30s'", message)
        self.assertIn("digits 'eight'", message)


class _ServicesConfig(LookupBase):
    def __init__(self, services: dict) -> None:
        """
        Args:
            services: the ``meta/services.yml`` content ``lookup('config', ...)`` answers from.
        """
        super().__init__()
        self.services = services

    def run(self, terms, variables=None, **kwargs):
        _application_id, path = terms
        value = {"services": self.services}
        for part in path.split("."):
            value = value[part]
        return [value]


def _deploy_holds(policy_overrides: dict) -> dict[str, bool]:
    """Evaluate the OTP variables and both asserts through Ansible as a deploy does.

    Args:
        policy_overrides: values replacing those of ``otp_policy``, keyed by its key names.

    Returns:
        Each ``<variable> is <test>`` and each assert condition, mapped to its result.
    """
    services = copy.deepcopy(SERVICES)
    services["keycloak"]["realm"]["otp_policy"].update(policy_overrides)
    config = _ServicesConfig(services)
    original = lookup_loader.get

    def get(name, *args, **kwargs):
        return config if name == "config" else original(name, *args, **kwargs)

    loader = DataLoader()
    variables = loader.load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    tasks = loader.load_from_file(str(INIT), trusted_as_template=True)
    conditions = [
        condition
        for task in tasks
        if task.get("name") in (POLICY_ASSERT, ENFORCED_ASSERT)
        for that in [task["ansible.builtin.assert"]["that"]]
        for condition in ([that] if isinstance(that, str) else that)
    ]
    templar = Templar(loader=loader, variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        results = {
            f"{name} is {test}": templar.evaluate_conditional(
                trust_as_template(f"{name} is {test}")
            )
            for name, test in OTP_VARIABLE_TESTS.items()
        }
        for condition in conditions:
            results[str(condition)] = templar.evaluate_conditional(condition)
    return results


class TestOtpAssertsAsDeployed(unittest.TestCase):
    def test_the_shipped_defaults_pass_every_type_test_and_assert(self) -> None:
        results = _deploy_holds({})
        self.assertEqual({}, {k: v for k, v in results.items() if v is not True})
        self.assertGreater(len(results), len(OTP_VARIABLE_TESTS))

    def test_a_quoted_number_in_the_policy_fails_the_integer_test(self) -> None:
        results = _deploy_holds({"digits": "6"})
        self.assertIs(False, results["KEYCLOAK_REALM_OTP_POLICY_DIGITS is integer"])


class TestVariantsSwitchEnforcementOff(unittest.TestCase):
    def test_the_shipped_default_enforces_totp(self) -> None:
        self.assertIs(True, SERVICES["keycloak"]["realm"]["totp_enforced"])

    def test_every_variant_switches_enforcement_off_and_passes_the_assert(
        self,
    ) -> None:
        variants = load_yaml_any(str(ROLE / ROLE_FILE_META_VARIANTS))
        self.assertTrue(variants)
        for index, variant in enumerate(variants):
            with self.subTest(variant=index):
                realm = variant["services"]["keycloak"].get("realm", {})
                self.assertIs(False, realm.get("totp_enforced"))
                effective = {**SERVICES["keycloak"]["realm"], **realm}
                self.assertTrue(
                    _holds(
                        ENFORCED_ASSERT,
                        {
                            "KEYCLOAK_REALM_TOTP_ENABLED": effective["totp_enabled"],
                            "KEYCLOAK_REALM_TOTP_ENFORCED": effective["totp_enforced"],
                        },
                    )
                )


class TestTotpEnforcedAssert(unittest.TestCase):
    def test_only_enforcing_without_offering_is_refused(self) -> None:
        for enabled, enforced, holds in (
            (True, False, True),
            (True, True, True),
            (False, False, True),
            (False, True, False),
        ):
            with self.subTest(enabled=enabled, enforced=enforced):
                self.assertIs(
                    holds,
                    _holds(
                        ENFORCED_ASSERT,
                        {
                            "KEYCLOAK_REALM_TOTP_ENABLED": enabled,
                            "KEYCLOAK_REALM_TOTP_ENFORCED": enforced,
                        },
                    ),
                )


if __name__ == "__main__":
    unittest.main()
