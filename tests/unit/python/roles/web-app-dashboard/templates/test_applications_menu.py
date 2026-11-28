"""The header's Apps menu, rendered from the folder grouping."""

from __future__ import annotations

import sys
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import dump_yaml_str, load_yaml_any, load_yaml_str

ROLE = PROJECT_ROOT / "roles" / "web-app-dashboard"
sys.path.insert(0, str(ROLE / "lookup_plugins"))

from docker_cards_grouped import group  # noqa: E402


def _card(card_id, *tags):
    return {
        "id": card_id,
        "title": card_id.title(),
        "text": f"{card_id} text",
        "icon": {"class": "fa-solid fa-cube"},
        "url": f"https://{card_id}.example",
        "iframe": False,
        "tags": list(tags),
    }


def _render(menu_data) -> dict:
    env = Environment(
        loader=FileSystemLoader(str(ROLE)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_nice_yaml"] = lambda value, indent: dump_yaml_str(
        value, sort_keys=False
    )
    rendered = env.get_template("templates/menu/applications.yml.j2").render(
        portfolio_menu_data=menu_data
    )
    return load_yaml_str(rendered)


class TestApplicationsMenu(unittest.TestCase):
    def test_the_apps_menu_nests_folders_and_lists_an_app_in_every_folder(self):
        folders = load_yaml_any(str(ROLE / "vars" / "menu_categories.yml"))[
            "portfolio_menu_categories"
        ]

        menu = _render(group([_card("listmonk", "listmonk")], folders))

        apps = menu["applications"][0]
        self.assertEqual(apps["name"], "Apps")
        paths = [
            (top["name"], sub["name"], [app["name"] for app in sub["children"]])
            for top in apps["children"]
            for sub in top["children"]
        ]
        self.assertEqual(
            paths,
            [
                ("Community & Social", "Community", ["Listmonk"]),
                ("Business", "Marketing", ["Listmonk"]),
            ],
        )
        self.assertEqual(
            apps["children"][1]["children"][0]["children"][0]["url"],
            "https://listmonk.example",
        )

    def test_no_card_leaves_the_apps_menu_empty(self):
        self.assertEqual(_render({"menu": []}), {"applications": None})


if __name__ == "__main__":
    unittest.main()
