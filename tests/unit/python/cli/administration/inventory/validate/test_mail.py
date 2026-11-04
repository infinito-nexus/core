import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.services.disabler import (
    DISABLED_SERVICES_RECORD,
)
from cli.administration.inventory.validate.mail import (
    group_hosts,
    validate_mail_wrapper,
    validate_mail_wrapper_for_roles,
)
from utils.cache.yaml import dump_yaml_str
from utils.mail.provider import MAIL_WRAPPER, provider_roles

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
STALWART = "web-app-stalwart"
MAILU = "web-app-mailu"
PROVIDERS = [STALWART, MAILU]


class TestValidateMailWrapper(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root)

    def _inventory(self, groups: dict[str, list[str]], name: str = "servers.yml"):
        children = {
            group: {"hosts": dict.fromkeys(hosts)} for group, hosts in groups.items()
        }
        (self.root / name).write_text(
            dump_yaml_str({"all": {"children": children}}), encoding="utf-8"
        )

    def _record(self, host: str, services: list[str]):
        (self.root / "host_vars").mkdir(exist_ok=True)
        (self.root / "host_vars" / f"{host}.yml").write_text(
            dump_yaml_str({DISABLED_SERVICES_RECORD: services}), encoding="utf-8"
        )

    def test_a_provider_without_the_wrapper_fails(self):
        self._inventory({STALWART: ["mail01"], "web-app-gitea": ["mail01"]})
        errors = validate_mail_wrapper(self.root, PROVIDERS)
        self.assertEqual(len(errors), 1)
        self.assertIn(f"'{STALWART}' is deployed on mail01", errors[0])
        self.assertIn(f"add {MAIL_WRAPPER} to the same hosts", errors[0])

    def test_the_wrapper_with_its_provider_passes(self):
        self._inventory({STALWART: ["mail01"], MAIL_WRAPPER: ["mail01"]})
        self.assertEqual(validate_mail_wrapper(self.root, PROVIDERS), [])

    def test_no_provider_passes(self):
        self._inventory({"web-app-gitea": ["app01"]})
        self.assertEqual(validate_mail_wrapper(self.root, PROVIDERS), [])

    def test_the_wrapper_on_another_host_fails_for_the_uncovered_host(self):
        self._inventory({STALWART: ["mail01", "mail02"], MAIL_WRAPPER: ["mail01"]})
        errors = validate_mail_wrapper(self.root, PROVIDERS)
        self.assertEqual(len(errors), 1)
        self.assertIn("on mail02 ", errors[0])

    def test_an_alternative_provider_without_the_wrapper_fails(self):
        self._inventory({MAILU: ["mail01"]})
        self.assertEqual(len(validate_mail_wrapper(self.root, PROVIDERS)), 1)

    def test_groups_split_across_files_are_merged(self):
        self._inventory({STALWART: ["mail01"]}, name="servers.yml")
        self._inventory({MAIL_WRAPPER: ["mail01"]}, name="wrapper.yml")
        self.assertEqual(group_hosts(self.root)[MAIL_WRAPPER], {"mail01"})
        self.assertEqual(validate_mail_wrapper(self.root, PROVIDERS), [])

    def test_a_disabled_wrapper_is_not_reported(self):
        self._inventory({STALWART: ["mail01"]})
        self._record("mail01", ["email"])
        self.assertEqual(validate_mail_wrapper(self.root, PROVIDERS), [])

    def test_another_disabled_service_does_not_excuse_the_wrapper(self):
        self._inventory({STALWART: ["mail01"]})
        self._record("mail01", ["tor"])
        self.assertEqual(len(validate_mail_wrapper(self.root, PROVIDERS)), 1)

    def test_the_roles_tree_supplies_every_covering_provider(self):
        self.assertEqual(set(PROVIDERS), set(provider_roles(ROLES_DIR)))
        self._inventory({MAILU: ["mail01"]})
        self.assertEqual(len(validate_mail_wrapper_for_roles(self.root, ROLES_DIR)), 1)


if __name__ == "__main__":
    unittest.main()
