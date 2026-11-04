import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from plugins.lookup.debug import LookupModule as DebugLookup
from plugins.lookup.validate import LookupModule as ValidateLookup

LOOKUPS = {"debug": (DebugLookup, "DEBUG"), "validate": (ValidateLookup, "VALIDATE")}


class _Config:
    def __init__(self, applications):
        self.applications = applications
        self.calls = []

    def run(self, terms, variables=None, roles_dir=None):
        self.calls.append(list(terms))
        node = self.applications.get(terms[0])
        if node is None:
            return [terms[2]]
        for key in terms[1].split("."):
            if not isinstance(node, dict) or key not in node:
                return [terms[2]]
            node = node[key]
        return [node]


def _lookup(switch, variables, applications=None, terms=(), templar=None):
    module_class, _ = LOOKUPS[switch]
    module = module_class()
    module._templar = templar
    module._loader = None
    config = _Config(applications or {})
    with mock.patch("plugins.lookup.debug.lookup_loader.get", return_value=config):
        return module.run(list(terms), variables=variables)[0], config


def _overriding(entity, switch, value):
    return {"services": {entity: {switch: {"enabled": value}}}}


class TestModeSwitchLookups(unittest.TestCase):
    def test_an_unset_switch_falls_back_to_the_global(self):
        for switch, (_, name) in LOOKUPS.items():
            for value in (True, False):
                with self.subTest(switch=switch, value=value):
                    result, _ = _lookup(
                        switch, {"application_id": "web-app-gitea", name: value}
                    )
                    self.assertIs(result, value)

    def test_a_set_override_wins_over_the_global_in_both_polarities(self):
        for switch, (_, name) in LOOKUPS.items():
            for value in (True, False):
                with self.subTest(switch=switch, value=value):
                    result, _ = _lookup(
                        switch,
                        {"application_id": "web-app-gitea", name: not value},
                        {"web-app-gitea": _overriding("gitea", switch, value)},
                    )
                    self.assertIs(result, value)

    def test_an_override_of_another_entity_is_not_read(self):
        result, _ = _lookup(
            "debug",
            {"application_id": "web-app-gitea", "DEBUG": False},
            {"web-app-gitea": _overriding("other", "debug", True)},
        )
        self.assertIs(result, False)

    def test_the_switch_path_uses_the_primary_entity(self):
        _, config = _lookup(
            "validate", {"application_id": "sys-svc-compose", "VALIDATE": True}
        )
        self.assertEqual(
            config.calls, [["sys-svc-compose", "services.svc-compose.validate", {}]]
        )

    def test_string_extra_vars_are_booleans(self):
        for switch, (_, name) in LOOKUPS.items():
            for raw, expected in (("true", True), ("false", False), ("False", False)):
                with self.subTest(switch=switch, raw=raw):
                    result, _ = _lookup(
                        switch, {"application_id": "web-app-gitea", name: raw}
                    )
                    self.assertIs(result, expected)

    def test_a_string_override_is_a_boolean(self):
        result, _ = _lookup(
            "debug",
            {"application_id": "web-app-gitea", "DEBUG": True},
            {"web-app-gitea": _overriding("gitea", "debug", "false")},
        )
        self.assertIs(result, False)

    def test_a_templated_global_is_rendered(self):
        variables = {
            "application_id": "web-app-gitea",
            "VALIDATE": trust_as_template("{{ 'true' | bool }}"),
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        result, _ = _lookup("validate", variables, templar=templar)
        self.assertIs(result, True)

    def test_the_term_overrides_application_id(self):
        result, config = _lookup(
            "debug",
            {"application_id": "web-app-gitea", "DEBUG": False},
            {"sys-svc-sshd": _overriding("svc-sshd", "debug", True)},
            terms=("sys-svc-sshd",),
        )
        self.assertIs(result, True)
        self.assertEqual(config.calls[0][0], "sys-svc-sshd")

    def test_neither_term_nor_application_id_fails_naming_the_lookup(self):
        for switch, (_, name) in LOOKUPS.items():
            with (
                self.subTest(switch=switch),
                self.assertRaisesRegex(AnsibleError, rf"lookup\('{switch}'\)"),
            ):
                _lookup(switch, {name: True})

    def test_an_undefined_global_fails(self):
        with self.assertRaisesRegex(AnsibleError, "DEBUG is not defined"):
            _lookup("debug", {"application_id": "web-app-gitea"})

    def test_a_non_boolean_value_fails(self):
        with self.assertRaisesRegex(AnsibleError, "not a boolean"):
            _lookup("debug", {"application_id": "web-app-gitea", "DEBUG": "maybe"})

    def test_a_switch_that_is_no_mapping_fails(self):
        with self.assertRaisesRegex(AnsibleError, "must be a mapping"):
            _lookup(
                "debug",
                {"application_id": "web-app-gitea", "DEBUG": False},
                {"web-app-gitea": {"services": {"gitea": {"debug": True}}}},
            )

    def test_more_than_one_term_fails(self):
        with self.assertRaisesRegex(AnsibleError, "at most one term"):
            _lookup("debug", {"DEBUG": True}, terms=("a", "b"))


if __name__ == "__main__":
    unittest.main()
