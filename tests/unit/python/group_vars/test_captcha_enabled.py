import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from ansible.utils.display import Display

from utils.cache.base import _render_with_templar
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_GENERAL_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "00_general.yml"
_ROLES_DIR = Path(PROJECT_ROOT) / "roles"
_PROVIDERS = {"recaptcha": "RECAPTCHA", "hcaptcha": "HCAPTCHA"}
_CREDENTIALS = {"KEY": "site-key", "SECRET": "site-secret"}


def _consumers() -> list[tuple[str, str, str]]:
    found = []
    for role_dir in sorted(_ROLES_DIR.iterdir()):
        services_file = role_dir / ROLE_FILE_META_SERVICES
        if not services_file.is_file():
            continue
        services = load_yaml_any(services_file) or {}
        for service_key, provider in _PROVIDERS.items():
            entry = services.get(service_key)
            enabled = entry.get("enabled") if isinstance(entry, dict) else None
            if isinstance(enabled, str) and f"{provider}_ENABLED" in enabled:
                found.append((role_dir.name, service_key, enabled))
    return found


class TestCaptchaEnabled(unittest.TestCase):
    """``services.<provider>.enabled`` reaches its consumers through the
    applications render, whose failure path hands back template text instead
    of raising. Inventory ``CAPTCHA`` replaces the group_vars mapping whole,
    so a host that configures one provider drops the other's sub-mapping.
    """

    group_vars: ClassVar[dict[str, Any]]
    consumers: ClassVar[list[tuple[str, str, str]]]

    @classmethod
    def setUpClass(cls):
        cls.group_vars = DataLoader().load_from_file(
            str(_GENERAL_VARS), trusted_as_template=True
        )
        cls.consumers = _consumers()

    def _render(self, value: str, captcha: dict[str, Any]) -> tuple[Any, list[str]]:
        variables = {**self.group_vars, "CAPTCHA": captcha}
        templar = Templar(loader=DataLoader(), variables=variables)
        with mock.patch.object(Display, "deprecated") as deprecated:
            rendered = _render_with_templar(value, templar=templar, variables=variables)
        coercions = [
            str(call) for call in deprecated.call_args_list if "coerced" in str(call)
        ]
        return rendered, coercions

    def _assert_every_consumer(self, captcha_for, expected_for):
        for role, service_key, value in self.consumers:
            provider = _PROVIDERS[service_key]
            with self.subTest(role=role, service=service_key):
                rendered, coercions = self._render(value, captcha_for(provider))
                self.assertIsInstance(rendered, bool, f"rendered to {rendered!r}")
                self.assertEqual(rendered, expected_for(provider))
                self.assertEqual(coercions, [])

    def test_every_provider_has_a_consumer(self):
        self.assertEqual(
            {service_key for _, service_key, _ in self.consumers}, set(_PROVIDERS)
        )

    def test_the_group_vars_defaults_disable_every_provider(self):
        self._assert_every_consumer(
            lambda provider: self.group_vars["CAPTCHA"], lambda provider: False
        )

    def test_both_credentials_enable_the_provider(self):
        self._assert_every_consumer(
            lambda provider: {name: dict(_CREDENTIALS) for name in _PROVIDERS.values()},
            lambda provider: True,
        )

    def test_a_host_that_configures_only_the_other_provider_disables_this_one(self):
        def only_the_other(provider):
            return {
                name: dict(_CREDENTIALS)
                for name in _PROVIDERS.values()
                if name != provider
            }

        self._assert_every_consumer(only_the_other, lambda provider: False)

    def test_a_host_that_configures_only_this_provider_enables_it(self):
        self._assert_every_consumer(
            lambda provider: {provider: dict(_CREDENTIALS)}, lambda provider: True
        )


if __name__ == "__main__":
    unittest.main()
