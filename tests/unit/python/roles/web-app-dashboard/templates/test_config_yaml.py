from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ROLE = PROJECT_ROOT / "roles" / "web-app-dashboard"
TEMPLATES = ROLE / "templates"
GATE = "/roles/web-app-listmonk/administrator"
STUBBED_MENUS = ("followus", "contact", "support", "header", "footer")


def _module(name: str, path: Path):
    """Load a role-local plugin module by path.

    Args:
        name: the module name to register.
        path: the plugin file.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grouping = _module(
    "docker_cards_grouped", ROLE / "lookup_plugins" / "docker_cards_grouped.py"
)
first_seen = _module("first_seen", ROLE / "filter_plugins" / "first_seen.py")


def _card(card_id: str, tags: list[str], extra: dict) -> dict:
    """Return a ``docker_cards`` entry.

    Args:
        card_id: the application id.
        tags: its galaxy tags.
        extra: further keys of the card.
    """
    return {
        "id": card_id,
        "title": card_id.title(),
        "text": f"{card_id} text",
        "icon": {"class": "fa-solid fa-cube"},
        "url": f"https://{card_id}.example",
        "link_text": f"Explore {card_id}",
        "iframe": True,
        "tags": tags,
        **extra,
    }


def _folder(**entry) -> dict:
    """Return a ``portfolio_menu_categories`` entry.

    Args:
        entry: the folder's ``tags``, ``children`` or ``fallback``.
    """
    return {"description": "Folder text", "icon": "fa-solid fa-folder", **entry}


CARDS = [
    _card("web-app-listmonk", ["newsletter"], {"allowed_groups": [GATE]}),
    _card("web-app-mailu", ["mail"], {}),
    _card("web-app-chess", ["no-folder-knows-this-tag"], {}),
]
TREE = {
    "Talk": _folder(children={"Mail": _folder(tags=["mail"])}),
    "Work": _folder(children={"Marketing": _folder(tags=["newsletter"])}),
    "Community": _folder(tags=["newsletter"]),
    "Empty": _folder(tags=["no-card-has-this-tag"]),
    "Other": _folder(fallback=True),
}
REGISTRY = {"web-app-listmonk": "", "web-app-mailu": "2026-11-01", "web-app-chess": ""}


def _render(*, folders: bool) -> dict:
    """Render ``config.yaml.j2`` through Ansible's templar, as the deploy does.

    Args:
        folders: the value of ``DASHBOARD_FOLDERS_ENABLED``.
    """
    variables = {
        "portfolio_menu_data": grouping.group(
            first_seen.with_added(CARDS, REGISTRY), TREE
        ),
        "DASHBOARD_FOLDERS_ENABLED": folders,
        "DASHBOARD_NEW_DAYS": "14",
        "DASHBOARD_PLATFORM_TITLE": "Platform",
        "DASHBOARD_PLATFORM_LOGO_URL": "https://asset.example/logo.png",
        "DASHBOARD_PLATFORM_FAVICON_URL": "https://asset.example/favicon.ico",
        "DASHBOARD_COMPANY_LOGO_URL": "https://asset.example/company.png",
        "service_provider": {
            "platform": {"subtitel": "Sub"},
            "company": {
                "titel": "Company",
                "slogan": "Slogan",
                "address": {"street": "Street 1"},
            },
            "legal": {"imprint": "https://example/imprint"},
        },
    }
    with tempfile.TemporaryDirectory() as stubs:
        (Path(stubs) / "menu").mkdir()
        for name in STUBBED_MENUS:
            (Path(stubs) / "menu" / f"{name}.yml.j2").write_text("")
        templar = Templar(loader=DataLoader(), variables=variables).copy_with_new_env(
            searchpath=[stubs, str(TEMPLATES)]
        )
        rendered = templar.template(
            trust_as_template(read_text(str(TEMPLATES / "config.yaml.j2"))),
            overrides={"trim_blocks": True},
        )
    return load_yaml_str(rendered)


def _folder_nodes(value) -> int:
    if isinstance(value, dict):
        own = 1 if {"slug", "children"} <= set(value) else 0
        return own + sum(_folder_nodes(item) for item in value.values())
    if isinstance(value, list):
        return sum(_folder_nodes(item) for item in value)
    return 0


class TestConfigYaml(unittest.TestCase):
    def test_every_card_carries_its_id_and_the_folder_paths_it_belongs_to(self):
        cards = {card["id"]: card for card in _render(folders=True)["cards"]}

        self.assertEqual(
            {card_id: card["folders"] for card_id, card in cards.items()},
            {
                "web-app-listmonk": ["work/marketing", "community"],
                "web-app-mailu": ["talk/mail"],
                "web-app-chess": ["other"],
            },
        )

    def test_the_folder_tree_is_emitted_once_under_the_dashboard(self):
        config = _render(folders=True)

        tree = config["dashboard"]["folders"]
        self.assertEqual(
            [node["slug"] for node in tree],
            ["talk", "work", "community", "other"],
        )
        self.assertEqual(_folder_nodes(config), _folder_nodes(tree))

    def test_the_config_carries_no_group_list(self):
        config = _render(folders=True)

        self.assertFalse(
            [card["id"] for card in config["cards"] if "allowed_groups" in card]
        )
        self.assertNotIn(GATE, str(config))

    def test_the_first_deploy_date_and_the_new_window_reach_port_ui(self):
        config = _render(folders=True)

        added = {card["id"]: card.get("added") for card in config["cards"]}
        self.assertEqual(
            added,
            {
                "web-app-listmonk": None,
                "web-app-mailu": "2026-11-01",
                "web-app-chess": None,
            },
        )
        self.assertEqual(config["dashboard"]["new_days"], 14)

    def test_the_folder_switch_off_drops_only_the_tree(self):
        config = _render(folders=False)

        self.assertNotIn("folders", config["dashboard"])
        self.assertEqual(config["dashboard"]["new_days"], 14)
        self.assertEqual(
            [card["id"] for card in config["cards"]],
            ["web-app-listmonk", "web-app-mailu", "web-app-chess"],
        )


if __name__ == "__main__":
    unittest.main()
