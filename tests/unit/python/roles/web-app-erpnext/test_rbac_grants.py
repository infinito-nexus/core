from __future__ import annotations

import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-erpnext"
GENERAL_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"
CHECK = "🔍 Check every entry of services.erpnext.group_roles"
APPEND = "combine(list_merge='append_rp')"
MANAGER = "/roles/web-app-erpnext/manager"
CORE = {
    "/roles/web-app-erpnext/administrator": ["System Manager"],
    MANAGER: ["Sales User", "Purchase User"],
}
MAPPED_GROUP = "/roles/web-app-consumer/auditor"
MAPPED = {"group": MAPPED_GROUP, "roles": ["Audit Editor"]}


def _load(path) -> Any:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _render(expression: str, variables: dict[str, Any]) -> Any:
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


class TestRbacGrants(unittest.TestCase):
    declared: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.declared = _load(ROLE / ROLE_FILE_VARS_MAIN)

    def _group_grants(self, group_roles, expression=None) -> dict[str, list[str]]:
        """Args:
            group_roles: the inventory's ``services.erpnext.group_roles``.
            expression: the merge to resolve, the declared one when None.

        Returns:
            ``ERPNEXT_RBAC_GROUP_GRANTS`` resolved.
        """
        source = expression or self.declared["ERPNEXT_RBAC_GROUP_GRANTS"]
        return _render(source, {"ERPNEXT_RBAC_GROUP_ROLES": group_roles})

    def _merge(self, group_roles, expression=None) -> dict[str, list[str]]:
        """Args:
            group_roles: the inventory's ``services.erpnext.group_roles``.
            expression: the merge to resolve, the declared one when None.

        Returns:
            ``ERPNEXT_RBAC_GRANTS`` resolved over fixed core grants.
        """
        source = expression or self.declared["ERPNEXT_RBAC_GRANTS"]
        return _render(
            source,
            {
                "ERPNEXT_RBAC_CORE_GRANTS": CORE,
                "ERPNEXT_RBAC_GROUP_GRANTS": self._group_grants(group_roles),
            },
        )

    def test_the_protected_owners_map_the_platform_admin_address_to_its_username(
        self,
    ) -> None:
        lookup = "lookup('users', 'platform_administrator')"
        source = self.declared["ERPNEXT_RBAC_PROTECTED_OWNERS"]
        self.assertIn(lookup, source)

        owners = _render(
            source.replace(lookup, "platform_administrator"),
            {
                "platform_administrator": {
                    "email": "PlatformAdmin@infinito.example",
                    "username": "platformadmin",
                }
            },
        )

        self.assertEqual(owners, {"PlatformAdmin@infinito.example": "platformadmin"})
        self.assertEqual(
            self.declared["ERPNEXT_LOGIN_RBAC_SETTINGS"]["protected_owners"],
            "{{ ERPNEXT_RBAC_PROTECTED_OWNERS }}",
        )

    def test_the_role_ships_no_group_roles(self) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertEqual(services["erpnext"]["group_roles"], [])

    def test_without_group_roles_the_core_grants_stay_as_they_are(self) -> None:
        self.assertEqual(self._group_grants([]), {})
        self.assertEqual(self._merge([]), CORE)

    def test_a_consumer_group_joins_the_merged_mapping_only(self) -> None:
        self.assertEqual(self._group_grants([MAPPED]), {MAPPED_GROUP: ["Audit Editor"]})
        self.assertEqual(
            self._merge([MAPPED]), {**CORE, MAPPED_GROUP: ["Audit Editor"]}
        )

    def test_a_core_group_mapped_again_keeps_its_core_roles(self) -> None:
        merged = self._merge([{"group": MANAGER, "roles": ["Stock Manager"]}])

        self.assertEqual(
            sorted(merged[MANAGER]), ["Purchase User", "Sales User", "Stock Manager"]
        )

    def test_a_merge_that_overwrites_loses_the_core_roles(self) -> None:
        overwriting = self.declared["ERPNEXT_RBAC_GRANTS"].replace(APPEND, "combine")
        self.assertNotEqual(overwriting, self.declared["ERPNEXT_RBAC_GRANTS"])

        merged = self._merge(
            [{"group": MANAGER, "roles": ["Stock Manager"]}], expression=overwriting
        )

        self.assertEqual(merged[MANAGER], ["Stock Manager"])

    def test_a_group_listed_twice_unites_its_roles(self) -> None:
        twice = [MAPPED, {"group": MAPPED_GROUP, "roles": ["Audit Viewer"]}]

        self.assertEqual(
            sorted(self._group_grants(twice)[MAPPED_GROUP]),
            ["Audit Editor", "Audit Viewer"],
        )

    def test_a_group_merge_that_overwrites_keeps_only_the_last_entry(self) -> None:
        declared = self.declared["ERPNEXT_RBAC_GROUP_GRANTS"]
        overwriting = declared.replace(APPEND, "combine")
        self.assertNotEqual(overwriting, declared)
        twice = [MAPPED, {"group": MAPPED_GROUP, "roles": ["Audit Viewer"]}]

        self.assertEqual(
            self._group_grants(twice, expression=overwriting)[MAPPED_GROUP],
            ["Audit Viewer"],
        )

    def test_every_consumer_reads_its_side_of_the_mapping(self) -> None:
        settings = self.declared["ERPNEXT_LOGIN_RBAC_SETTINGS"]
        rbac = _load(ROLE / "tasks" / "04_rbac.yml")[0]["vars"]
        ldap = _load(ROLE / "tasks" / "03_ldap.yml")[0]["environment"]
        playwright = read_text(str(ROLE / "templates" / "playwright.env.j2"))

        self.assertEqual(settings["role_grants"], "{{ ERPNEXT_RBAC_CORE_GRANTS }}")
        self.assertEqual(settings["group_roles"], "{{ ERPNEXT_RBAC_GROUP_GRANTS }}")
        self.assertEqual(rbac["rbac_sync_roles"], "{{ ERPNEXT_RBAC_GRANTS | list }}")
        self.assertEqual(
            rbac["rbac_sync_env"]["ROLE_GRANTS_JSON"],
            "{{ ERPNEXT_RBAC_CORE_GRANTS | to_json }}",
        )
        self.assertEqual(
            rbac["rbac_sync_env"]["GROUP_ROLES_JSON"],
            "{{ ERPNEXT_RBAC_GROUP_GRANTS | to_json }}",
        )
        self.assertEqual(
            ldap["ROLE_GRANTS_JSON"], "{{ ERPNEXT_RBAC_CORE_GRANTS | to_json }}"
        )
        self.assertEqual(
            ldap["GROUP_ROLES_JSON"], "{{ ERPNEXT_RBAC_GROUP_GRANTS | to_json }}"
        )
        self.assertIn(
            "RBAC_MANAGED_ROLES_JSON={{ ERPNEXT_RBAC_GRANTS | dict2items", playwright
        )

    def test_one_condition_decides_directory_ids_and_the_directory_connection(
        self,
    ) -> None:
        sync = _load(ROLE / "tasks" / "04_rbac.yml")[0]["vars"]["rbac_sync_env"]
        ldap_include = next(
            task
            for task in _load(ROLE / "tasks" / "01_manager_ops.yml")
            if task.get("include_tasks") == "03_ldap.yml"
        )
        login = self.declared["ERPNEXT_LOGIN_RBAC_SETTINGS"]

        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                variables = {
                    "ERPNEXT_LDAP_ENABLED": enabled,
                    "group_names": ["svc-db-openldap"],
                }
                connects = _render("{{ " + ldap_include["when"] + " }}", variables)
                self.assertEqual(connects, enabled)
                self.assertEqual(
                    _render(sync["DIRECTORY_IDS_JSON"], variables),
                    "true" if enabled else "false",
                )
                self.assertEqual(_render(login["directory_ids"], variables), enabled)


class TestGroupRolesCheck(unittest.TestCase):
    declared: ClassVar[dict[str, Any]]
    tasks: ClassVar[list[dict[str, Any]]]
    pattern: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.declared = _load(ROLE / ROLE_FILE_VARS_MAIN)
        cls.tasks = _load(ROLE / "tasks" / "utils" / "stack" / "guard.yml")
        rbac = load_yaml_any(str(GENERAL_VARS))["RBAC"]
        cls.pattern = _render(
            cls.declared["ERPNEXT_RBAC_GROUP_PATTERN"], {"RBAC": rbac}
        )

    def _check(self) -> dict[str, Any]:
        return next(task for task in self.tasks if task.get("name") == CHECK)

    def _passes(self, entry) -> bool:
        variables = {
            "item": entry,
            "ERPNEXT_RBAC_GROUP_PATTERN": self.pattern,
            "ERPNEXT_RBAC_ROLE_GRANTS": self.declared["ERPNEXT_RBAC_ROLE_GRANTS"],
            "ERPNEXT_RBAC_RESERVED_ROLES": self.declared["ERPNEXT_RBAC_RESERVED_ROLES"],
        }
        return all(
            _render("{{ " + condition + " }}", variables)
            for condition in self._check()["ansible.builtin.assert"]["that"]
        )

    def test_the_pattern_anchors_the_tenantless_group_of_the_rbac_root(self) -> None:
        self.assertEqual(self.pattern, "^/roles/[a-z0-9-]+/[a-z0-9-]+\\Z")

    def test_a_group_of_another_application_passes(self) -> None:
        self.assertTrue(self._passes(MAPPED))
        self.assertTrue(
            self._passes({"group": MANAGER, "roles": ["Stock Manager", "Audit Editor"]})
        )

    def test_every_other_group_path_fails_the_deploy(self) -> None:
        for group in (
            "roles/web-app-consumer/auditor",
            "@users",
            "/wrong/app/role",
            "//roles/web-app-consumer/auditor",
            "/roles/web-app-consumer/t.example/auditor",
            "/roles/web-app-consumer",
            "/roles/web-app-consumer/auditor/",
            "/roles/web-app-consumer/auditor\n",
            "/roles/web-app-consumer/audi*tor",
            "/roles/web-app-(consumer)/auditor",
            "/roles/web-app-consumer/{0}",
            "/roles/Web-App-Consumer/auditor",
            "/roles/web-app-consumer/auditor)(uid=*",
            42,
        ):
            with self.subTest(group=group):
                self.assertFalse(self._passes({**MAPPED, "group": group}))

    def test_roles_must_be_a_non_empty_list_of_roles_core_does_not_grant(
        self,
    ) -> None:
        for roles in (
            [],
            "Audit Editor",
            {"Audit Editor": True},
            ["Customer"],
            ["customer"],
            ["Audit Editor", "Stock User"],
            ["System Manager"],
            ["SYSTEM MANAGER"],
            ["Administrator"],
            ["guest"],
            ["All"],
            ["Audit Editor", 7],
        ):
            with self.subTest(roles=roles):
                self.assertFalse(self._passes({**MAPPED, "roles": roles}))

    def test_the_check_loops_over_the_inventory_in_the_stack_guard(self) -> None:
        check = self._check()
        self.assertEqual(check["loop"], "{{ ERPNEXT_RBAC_GROUP_ROLES }}")
        core = _load(ROLE / "tasks" / "00_core.yml")
        self.assertNotIn(CHECK, [task.get("name") for task in core])


if __name__ == "__main__":
    unittest.main()
