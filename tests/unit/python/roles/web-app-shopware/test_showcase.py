from __future__ import annotations

import json
import os
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-shopware"
PLAYWRIGHT_ENV = ROLE / "templates/playwright.env.j2"
RUNTIME_GATE = re.compile(r"RUNTIME in \[[^\]]*\]")
SEED = "Seed the showcase"
SHOWCASE = {
    "customerEmail": "design-showcase@shop.example",
    "products": [{"id": "d0000000000000000000000000000011", "name": "Lamp"}],
}


def _vars() -> dict:
    return DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )


def _gate(design: bool, runtime: str) -> bool:
    templar = Templar(
        loader=DataLoader(),
        variables={"SHOPWARE_DESIGN_ENABLED": design, "RUNTIME": runtime},
    )
    return str(templar.template(_vars()["SHOPWARE_SHOWCASE_ENABLED"])) == "True"


def _seed_task() -> dict:
    return next(
        task
        for task in load_yaml_any(str(ROLE / "tasks/05_design.yml"))
        if SEED in task["name"]
    )


def _showcase_env(seeded: dict) -> dict[str, str]:
    """
    Args:
        seeded: what ``SHOPWARE_SHOWCASE_SEEDED`` holds.

    Returns:
        ``{key: value}`` of the ``SHOWCASE_*`` lines of the spec env, rendered.
    """
    lines = [
        line
        for line in read_text(str(PLAYWRIGHT_ENV)).splitlines()
        if line.startswith("SHOWCASE_")
    ]
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["dotenv_quote"] = str
    env.filters["to_json"] = json.dumps
    rendered = env.from_string("\n".join(lines)).render(
        SHOPWARE_SHOWCASE=SHOWCASE, SHOPWARE_SHOWCASE_SEEDED=seeded
    )
    return dict(line.split("=", 1) for line in rendered.splitlines())


def _role_text(*parts: str) -> str:
    return "\n".join(
        read_text(path)
        for path in iter_project_files()
        if path.startswith(str(ROLE.joinpath(*parts)) + os.sep)
    )


class TestShowcaseSeed(unittest.TestCase):
    def test_the_seed_runs_where_playwright_runs_and_the_design_is_on(self) -> None:
        for runtime in ("dev", "act", "github"):
            with self.subTest(runtime=runtime):
                self.assertTrue(_gate(True, runtime))

    def test_negative_control_no_seed_on_a_production_runtime_or_without_design(
        self,
    ) -> None:
        for design, runtime in (
            (True, "host"),
            (True, "production"),
            (True, ""),
            (False, "dev"),
        ):
            with self.subTest(design=design, runtime=runtime):
                self.assertFalse(_gate(design, runtime))

    def test_the_runtime_list_is_the_one_the_playwright_stage_gates_on(self) -> None:
        stage = read_text(str(PROJECT_ROOT / "tasks/stages/02_server.yml"))
        playwright = stage[stage.index("test-e2e-playwright") :]
        self.assertEqual(
            RUNTIME_GATE.findall(_vars()["SHOPWARE_SHOWCASE_ENABLED"]),
            RUNTIME_GATE.findall(playwright)[:1],
        )

    def test_only_variant_zero_enables_the_design_that_seeds(self) -> None:
        variants = load_yaml_any(str(ROLE / ROLE_FILE_META_VARIANTS))
        self.assertEqual(
            [
                index
                for index, variant in enumerate(variants)
                if variant["services"]["design"]["enabled"]
            ],
            [0],
        )

    def test_the_seed_task_is_gated_masked_and_idempotent(self) -> None:
        task = _seed_task()
        self.assertEqual(task["when"], "SHOPWARE_SHOWCASE_ENABLED | bool")
        self.assertEqual(task["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
        self.assertEqual(
            task["changed_when"],
            "(shopware_design_showcase.stdout_lines | last | from_json).changed",
        )

    def test_the_task_pipes_the_real_scripts_and_hands_in_no_credential(self) -> None:
        command = _seed_task()["ansible.builtin.shell"]
        self.assertEqual(
            command["stdin"].splitlines(),
            [
                "{{ lookup('ansible.builtin.file', role_path ~ '/files/php/dal.php') }}",
                "{{ lookup('ansible.builtin.file', role_path ~ '/files/php/design/showcase.php') }}",
            ],
        )
        self.assertNotRegex(command["cmd"], r"(?i)password|secret|lookup\('users'")

    def test_the_design_spec_gets_the_seed_through_env_and_no_key(self) -> None:
        seeded = {
            "channelId": "c1",
            "customerPassword": "derived",
            "themeConfig": {"sw-color-brand-primary": "#123456"},
            "themeId": "t1",
        }
        self.assertEqual(
            _showcase_env(seeded),
            {
                "SHOWCASE_CHANNEL_ID": "c1",
                "SHOWCASE_CUSTOMER_EMAIL": SHOWCASE["customerEmail"],
                "SHOWCASE_CUSTOMER_PASSWORD": "derived",
                "SHOWCASE_PRODUCT_ID": SHOWCASE["products"][0]["id"],
                "SHOWCASE_PRODUCT_NAME": SHOWCASE["products"][0]["name"],
                "SHOWCASE_THEME_CONFIG": json.dumps(seeded["themeConfig"]),
                "SHOWCASE_THEME_ID": "t1",
            },
        )
        unseeded = _showcase_env({})
        self.assertEqual(unseeded["SHOWCASE_CUSTOMER_PASSWORD"], "")
        self.assertEqual(unseeded["SHOWCASE_THEME_CONFIG"], "{}")
        keys = re.findall(r"^(\w+)=", read_text(str(PLAYWRIGHT_ENV)), re.MULTILINE)
        self.assertEqual([key for key in keys if "INTEGRATION" in key], [])

    def test_the_seed_output_reaches_the_spec_only_where_it_was_seeded(self) -> None:
        seeded = {"changed": False, "customerPassword": "derived"}
        for enabled, registered, expected in (
            (
                True,
                {"stdout_lines": ["CHANGED customer c", json.dumps(seeded)]},
                seeded,
            ),
            (False, {"skipped": True}, {}),
        ):
            with self.subTest(enabled=enabled):
                templar = Templar(
                    loader=DataLoader(),
                    variables={
                        "SHOPWARE_SHOWCASE_ENABLED": enabled,
                        "shopware_design_showcase": registered,
                    },
                )
                self.assertEqual(
                    templar.template(_vars()["SHOPWARE_SHOWCASE_SEEDED"]), expected
                )

    def test_no_role_ships_spec_secrets(self) -> None:
        self.assertEqual(
            [
                path
                for path in iter_project_files()
                if path.endswith(
                    os.sep + "templates" + os.sep + "playwright.secrets.j2"
                )
            ],
            [],
        )

    def test_the_removed_design_integration_stays_removed(self) -> None:
        for part in ("tasks", "files", "templates", "vars", "meta"):
            with self.subTest(part=part):
                text = _role_text(part)
                for needle in (
                    "integration.php",
                    "'integration'",
                    "DESIGN_INTEGRATION",
                    "shopware_design_integration_keys",
                ):
                    self.assertNotIn(needle, text)

    def test_negative_control_the_integration_scan_sees_the_role_files(self) -> None:  # nocheck: test.text-presence -- control that the role-wide scan reads the role files  # fmt: skip
        self.assertIn("showcase.php", _role_text("tasks"))


if __name__ == "__main__":
    unittest.main()
