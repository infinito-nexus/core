"""Enabling Multisite without domain tenancy fails the deploy before anything else runs."""

from __future__ import annotations

import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.applications import get_variants
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APPLICATION_ID = "web-app-wordpress"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
ROLE_VARS = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
CORE_TASKS = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"))
ASSERT_NAME = "✅ Assert Multisite runs with domain tenancy"


def _env() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = to_bool
    return env


def _expression(source: str, **variables: object) -> object:
    return _env().compile_expression(source)(**variables)


def _var_expression(name: str) -> str:
    return ROLE_VARS[name].strip().removeprefix("{{").removesuffix("}}")


def _domain_tenancy(rbac: dict) -> bool:
    def lookup(*terms: str) -> object:
        if terms != ("config", APPLICATION_ID, "rbac"):
            raise AssertionError(f"the tenancy vars render an unexpected lookup{terms}")
        return rbac

    config = _expression(
        _var_expression("WORDPRESS_RBAC_CONFIG"),
        application_id=APPLICATION_ID,
        lookup=lookup,
    )
    return _expression(
        _var_expression("WORDPRESS_RBAC_DOMAIN_TENANCY"), WORDPRESS_RBAC_CONFIG=config
    )


def _assert_task() -> dict:
    tasks = [task for task in CORE_TASKS if task.get("name") == ASSERT_NAME]
    if len(tasks) != 1:
        raise AssertionError(
            f"00_core.yml holds {len(tasks)} tasks named {ASSERT_NAME}"
        )
    return tasks[0]


def _deploy_fails(multisite: bool, rbac: dict) -> bool:
    task = _assert_task()
    variables = {
        "WORDPRESS_MULTISITE_ENABLED": multisite,
        "WORDPRESS_RBAC_DOMAIN_TENANCY": _domain_tenancy(rbac),
    }
    if not _expression(task["when"], **variables):
        return False
    return not _expression(task["ansible.builtin.assert"]["that"], **variables)


class TestMultisiteTenancy(unittest.TestCase):
    def test_multisite_without_tenancy_fails_the_deploy(self) -> None:
        self.assertTrue(_deploy_fails(True, {"roles": {}}))

    def test_multisite_with_tenancy_none_fails_the_deploy(self) -> None:
        self.assertTrue(_deploy_fails(True, {"tenancy": {"axis": "none"}}))

    def test_multisite_with_domain_tenancy_passes(self) -> None:
        self.assertFalse(_deploy_fails(True, {"tenancy": {"axis": "domain"}}))

    def test_a_single_site_needs_no_tenancy(self) -> None:
        self.assertFalse(_deploy_fails(False, {"roles": {}}))

    def test_the_failure_names_the_missing_tenancy(self) -> None:
        message = (
            _env()
            .from_string(_assert_task()["ansible.builtin.assert"]["fail_msg"])
            .render(application_id=APPLICATION_ID)
        )

        self.assertIn("rbac.tenancy.axis", message)
        self.assertIn("'domain'", message)
        self.assertIn(APPLICATION_ID, message)

    def test_the_check_runs_before_the_role_deploys_anything(self) -> None:
        index = CORE_TASKS.index(_assert_task())
        earlier = [
            task
            for task in CORE_TASKS[:index]
            if "include_role" in task or "stack_host_template" in task
        ]

        self.assertEqual(earlier, [])

    def test_every_multisite_variant_declares_domain_tenancy(self) -> None:
        variants = get_variants(roles_dir=PROJECT_ROOT / "roles")[APPLICATION_ID]
        multisite = {
            index: variant
            for index, variant in enumerate(variants)
            if variant["services"]["wordpress"].get("multisite", {}).get("enabled")
        }
        self.assertTrue(multisite, "no WordPress variant runs Multisite")
        for index, variant in multisite.items():
            with self.subTest(variant=index):
                self.assertTrue(_domain_tenancy(variant["rbac"]))


if __name__ == "__main__":
    unittest.main()
