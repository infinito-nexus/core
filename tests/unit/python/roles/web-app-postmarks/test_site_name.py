from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = "web-app-postmarks"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
PATCHER = "javascript/patch_site_name.js"


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestPostmarksSiteName(unittest.TestCase):
    variables: ClassVar[dict] = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))

    def _site_name(self, design_enabled) -> str:
        """Render POSTMARKS_SITE_NAME against stubbed lookups.

        Args:
            design_enabled: what ``lookup('config', ..., 'services.design.enabled')`` answers.

        Returns:
            The rendered value, where ``lookup('design', ...)`` resolves the label
            ``Bookmarks Hub`` and the README name ``Postmarks``.
        """
        answers = {
            "config": design_enabled,
            "design": {"label": "Bookmarks Hub", "name": "Postmarks"},
        }
        env = Environment(undefined=StrictUndefined, autoescape=True)
        env.filters["bool"] = _ansible_bool
        env.globals["lookup"] = lambda name, *_terms: answers[name]
        return env.from_string(self.variables["POSTMARKS_SITE_NAME"]).render(
            application_id=ROLE
        )

    def test_an_enabled_design_names_the_site_by_its_label(self) -> None:
        self.assertEqual(self._site_name(True), "Bookmarks Hub")

    def test_a_disabled_design_names_the_site_by_the_role_name(self) -> None:
        self.assertEqual(self._site_name(False), "Postmarks")

    def test_the_container_env_hands_the_site_name_to_the_server(self) -> None:
        env = dict(
            re.findall(
                r"^([A-Z][A-Z0-9_]*)=(.*)$",
                read_text(str(ROLE_DIR / "templates" / "env.j2")),
                re.MULTILINE,
            )
        )

        self.assertEqual(env["SITE_NAME"], "{{ POSTMARKS_SITE_NAME | dotenv_quote }}")

    def test_the_image_build_applies_the_staged_patch(self) -> None:
        staged = [
            item["dest"]
            for task in load_yaml_any(str(ROLE_DIR / "tasks" / "00_core.yml"))
            for item in task.get("loop") or []
            if isinstance(item, dict) and item.get("src") == PATCHER
        ]
        self.assertEqual(len(staged), 1, f"{PATCHER} must reach the build context once")

        dockerfile = read_text(str(ROLE_DIR / "files" / "Dockerfile"))
        copied = re.search(
            rf"^COPY {re.escape(staged[0])} (\S+)$", dockerfile, re.MULTILINE
        )
        self.assertIsNotNone(copied, "the build stage must copy the staged patch")
        self.assertRegex(
            dockerfile,
            rf"(?m)^RUN node {re.escape(copied.group(1))} /app/server\.js\b",
            "the build stage must run the patch on server.js",
        )


if __name__ == "__main__":
    unittest.main()
