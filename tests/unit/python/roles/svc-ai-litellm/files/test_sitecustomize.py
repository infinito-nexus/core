from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch

from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/python/sitecustomize.py"
ADDRESS = f"platformadmin@{default_domain_primary()}"


def fake_email_validator() -> types.ModuleType:
    """Build the slice of email-validator 2.3 the gateway's SSO path runs.

    Returns:
        a module whose ``validate`` rejects a special-use domain the way
        ``email_validator.syntax.validate_email_domain_name`` does.
    """
    module = types.ModuleType("email_validator")
    module.SPECIAL_USE_DOMAIN_NAMES = [
        "arpa",
        "invalid",
        "local",
        "localhost",
        "onion",
        "test",
    ]

    def validate(address: str) -> str:
        domain = address.rsplit("@", 1)[1]
        for name in module.SPECIAL_USE_DOMAIN_NAMES:
            if domain == name or domain.endswith("." + name):
                raise ValueError(
                    "The part after the @-sign is a special-use or reserved name"
                )
        return address

    module.validate = validate
    return module


def start_interpreter(environment: dict[str, str]) -> types.ModuleType:
    """Run the hook as the interpreter does at start, against a fake validator.

    Args:
        environment: the gateway container's environment.

    Returns:
        the email-validator module the hook mutated.
    """
    validator = fake_email_validator()
    with (
        patch.dict(sys.modules, {"email_validator": validator}),
        patch.dict(os.environ, environment, clear=True),
    ):
        spec = importlib.util.spec_from_file_location("sitecustomize", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return validator


class TestSitecustomize(unittest.TestCase):
    def test_negative_control_the_validator_refuses_the_ci_admin_address(self) -> None:
        with self.assertRaises(ValueError):
            fake_email_validator().validate(ADDRESS)

    def test_the_platform_tld_lets_the_sso_email_validate(self) -> None:
        validator = start_interpreter({"LITELLM_EMAIL_TLD": "test"})
        self.assertEqual(validator.validate(ADDRESS), ADDRESS)

    def test_only_the_platform_tld_is_admitted(self) -> None:
        validator = start_interpreter({"LITELLM_EMAIL_TLD": "test"})
        self.assertEqual(
            validator.SPECIAL_USE_DOMAIN_NAMES,
            ["arpa", "invalid", "local", "localhost", "onion"],
        )

    def test_a_public_tld_changes_nothing(self) -> None:
        validator = start_interpreter({"LITELLM_EMAIL_TLD": "com"})
        self.assertIn("test", validator.SPECIAL_USE_DOMAIN_NAMES)
        with self.assertRaises(ValueError):
            validator.validate(ADDRESS)

    def test_without_the_variable_the_validator_is_untouched(self) -> None:
        validator = start_interpreter({})
        self.assertIn("test", validator.SPECIAL_USE_DOMAIN_NAMES)


if __name__ == "__main__":
    unittest.main()
