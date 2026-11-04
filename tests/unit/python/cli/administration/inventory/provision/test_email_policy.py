import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.email_policy import (
    apply_email_policy,
    carry_email_policy,
    inventory_is_new,
)
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.mail.policy import POLICY_EXTERNAL
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

REPO_ROLES = PROJECT_ROOT / "roles"
KEYCLOAK_VARIANTS = REPO_ROLES / "web-app-keycloak" / ROLE_FILE_META_VARIANTS
HOST_VARS = "# operator note\nansible_host: 10.0.0.1\n"
MAIL_APPS = ["web-app-keycloak", "web-app-stalwart", "svc-db-openldap"]
PREVIOUS = (
    "applications:\n  web-app-keycloak:\n    services:\n      keycloak:\n"
    "        email:\n          policy: mailbox\n          switch: true\n"
    "          secondary_required: false\n"
)


def _text(path):
    return path.read_text(encoding="utf-8")  # nocheck: cache-read -- tempdir


def _email(path):
    return load_yaml_any(str(path))["applications"]["web-app-keycloak"]["services"][
        "keycloak"
    ]["email"]


class TestApplyEmailPolicy(unittest.TestCase):
    def _apply(
        self,
        tmp,
        apps,
        new_inventory,
        content=HOST_VARS,
        roles=REPO_ROLES,
        variant=None,
    ):
        host_vars = Path(tmp) / "host.yml"
        host_vars.write_text(content, encoding="utf-8")
        written = apply_email_policy(
            host_vars_file=host_vars,
            application_ids=apps,
            host="host",
            roles_dir=roles,
            new_inventory=new_inventory,
            keycloak_variant=variant,
        )
        return written, host_vars

    def test_a_keycloak_variant_that_pins_the_policy_keeps_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            written, host_vars = self._apply(
                tmp, MAIL_APPS, True, roles=REPO_ROLES, variant=1
            )
            self.assertEqual(_text(host_vars), HOST_VARS)
        self.assertFalse(written)

    def test_a_keycloak_variant_pins_only_the_default_policy(self):
        variants = load_yaml_any(str(KEYCLOAK_VARIANTS))
        pinned = {
            v["services"]["keycloak"]["email"]["policy"]
            for v in variants
            if "email" in v.get("services", {}).get("keycloak", {})
        }
        self.assertEqual(pinned, {POLICY_EXTERNAL})

    def test_a_keycloak_variant_runs_the_external_policy_with_mail_and_directory(self):
        variants = load_yaml_any(str(KEYCLOAK_VARIANTS))
        existing_install = [
            index
            for index, v in enumerate(variants)
            if v["services"]["keycloak"].get("email", {}).get("policy")
            == POLICY_EXTERNAL
            and v["services"]["email"] == {"enabled": True, "shared": True}
            and v["services"]["ldap"] == {"enabled": True, "shared": True}
        ]
        self.assertTrue(existing_install)
        with tempfile.TemporaryDirectory() as tmp:
            written, _ = self._apply(
                tmp, MAIL_APPS, True, roles=REPO_ROLES, variant=existing_install[0]
            )
        self.assertFalse(written)

    def test_a_new_inventory_with_the_mail_provider_records_mailboxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            written, host_vars = self._apply(tmp, MAIL_APPS, True)
            policy = _email(host_vars)["policy"]
            text = _text(host_vars)
        self.assertTrue(written)
        self.assertEqual(policy, "mailbox")
        self.assertIn("# operator note", text)

    def test_a_new_inventory_without_the_directory_stays_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            written, host_vars = self._apply(
                tmp, ["web-app-keycloak", "web-app-stalwart"], True
            )
            self.assertEqual(_text(host_vars), HOST_VARS)
        self.assertFalse(written)

    def test_an_existing_inventory_is_never_switched(self):
        with tempfile.TemporaryDirectory() as tmp:
            written, host_vars = self._apply(tmp, MAIL_APPS, False)
            self.assertEqual(_text(host_vars), HOST_VARS)
        self.assertFalse(written)

    def test_a_policy_the_operator_set_is_kept(self):
        content = (
            "applications:\n  web-app-keycloak:\n    services:\n      keycloak:\n"
            "        email:\n          policy: external\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            written, host_vars = self._apply(
                tmp, ["web-app-stalwart"], True, content=content
            )
            self.assertEqual(_text(host_vars), content)
        self.assertFalse(written)


class TestInventoryIsNew(unittest.TestCase):
    def _is_new(self, tmp):
        root = Path(tmp)
        return inventory_is_new(
            inventory_file=root / "devices.yml", host_vars_dir=root / "host_vars"
        )

    def test_an_empty_folder_is_a_new_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self._is_new(tmp))

    def test_an_empty_host_vars_folder_is_still_a_new_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "host_vars").mkdir()
            self.assertTrue(self._is_new(tmp))

    def test_host_vars_without_devices_yml_belong_to_an_existing_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "host_vars").mkdir()
            (Path(tmp) / "host_vars" / "host.yml").write_text(
                HOST_VARS, encoding="utf-8"
            )
            self.assertFalse(self._is_new(tmp))

    def test_a_devices_yml_marks_an_existing_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "devices.yml").write_text("all: {}\n", encoding="utf-8")
            self.assertFalse(self._is_new(tmp))


class TestCarryEmailPolicy(unittest.TestCase):
    def _carry(self, tmp, previous):
        previous_file = Path(tmp) / "previous.yml"
        previous_file.write_text(previous, encoding="utf-8")
        host_vars = Path(tmp) / "host.yml"
        host_vars.write_text(HOST_VARS, encoding="utf-8")
        carried = carry_email_policy(
            previous_host_vars_file=previous_file, host_vars_file=host_vars
        )
        return carried, host_vars

    def test_the_policy_and_switch_of_the_replaced_inventory_carry_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            carried, host_vars = self._carry(tmp, PREVIOUS)
            email = _email(host_vars)
            text = _text(host_vars)
        self.assertTrue(carried)
        self.assertEqual(email, {"policy": "mailbox", "switch": True})
        self.assertIn("# operator note", text)

    def test_a_replaced_inventory_without_a_policy_carries_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            carried, host_vars = self._carry(tmp, HOST_VARS)
            self.assertEqual(_text(host_vars), HOST_VARS)
        self.assertFalse(carried)

    def test_a_carried_external_policy_blocks_the_mailbox_default(self):
        previous = PREVIOUS.replace("mailbox", "external")
        with tempfile.TemporaryDirectory() as tmp:
            self._carry(tmp, previous)
            host_vars = Path(tmp) / "host.yml"
            written = apply_email_policy(
                host_vars_file=host_vars,
                application_ids=MAIL_APPS,
                host="host",
                roles_dir=REPO_ROLES,
                new_inventory=True,
                keycloak_variant=None,
            )
            policy = _email(host_vars)["policy"]
        self.assertFalse(written)
        self.assertEqual(policy, POLICY_EXTERNAL)

    def test_a_missing_replaced_inventory_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(FileNotFoundError):
            carry_email_policy(
                previous_host_vars_file=Path(tmp) / "missing.yml",
                host_vars_file=Path(tmp) / "host.yml",
            )


if __name__ == "__main__":
    unittest.main()
