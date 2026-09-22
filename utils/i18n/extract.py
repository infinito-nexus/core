"""The translatable strings core ships, keyed by the ``msgctxt`` of their source."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.i18n.catalog import LOCALE_DIR, read_catalog
from utils.roles.mapping import ROLE_FILE_META_MAIN

CATEGORIES_FILE = Path("meta") / "categories.yml"
MENU_FILE = Path("roles") / "web-app-dashboard" / "vars" / "menu_categories.yml"
LOGOUT_FILE = Path("roles") / "web-app-keycloak" / "files" / "logout_i18n.yml"
DOCS_TOOLING = Path("roles") / "web-app-docs" / "files" / "python"
CATEGORY_FIELDS = ("title", "description")


def role_context(role: str) -> str:
    """Return the ``msgctxt`` of the description of ``role``.

    Args:
        role: role directory name.
    """
    return f"role:{role}:description"


def category_context(path: str, field: str) -> str:
    """Return the ``msgctxt`` of a field of the category at ``path``.

    Args:
        path: dotted category path, e.g. ``web.app``.
        field: ``title`` or ``description``.
    """
    return f"category:{path}:{field}"


def menu_context(key: str, field: str) -> str:
    """Return the ``msgctxt`` of a field of the dashboard menu category ``key``.

    Args:
        key: menu category name as written in ``menu_categories.yml``.
        field: ``title`` or ``description``.
    """
    return f"menu:{key}:{field}"


def logout_context(key: str) -> str:
    """Return the ``msgctxt`` of the logout panel string ``key``.

    Args:
        key: key in ``logout_i18n.yml``.
    """
    return f"logout:{key}"


def _load(path: Path):
    return load_yaml_any(path)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def role_messages(root: Path) -> list[tuple[str, str]]:
    messages = []
    roles = root / "roles"
    for main in sorted(roles.glob(f"*/{ROLE_FILE_META_MAIN}")):
        galaxy_info = (_load(main) or {}).get("galaxy_info") or {}
        description = _text(galaxy_info.get("description"))
        if description:
            role = main.relative_to(roles).parts[0]
            messages.append((role_context(role), description))
    return messages


def category_messages(root: Path) -> list[tuple[str, str]]:
    messages = []

    def walk(node: dict, path: list[str]) -> None:
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            dotted = ".".join([*path, key])
            for field in CATEGORY_FIELDS:
                text = _text(value.get(field))
                if text:
                    messages.append((category_context(dotted, field), text))
            walk(value, [*path, key])

    walk(_load(root / CATEGORIES_FILE)["roles"], [])
    return messages


def menu_messages(root: Path) -> list[tuple[str, str]]:
    messages = []
    for key, entry in _load(root / MENU_FILE)["portfolio_menu_categories"].items():
        messages.append((menu_context(key, "title"), key))
        description = _text(entry.get("description"))
        if description:
            messages.append((menu_context(key, "description"), description))
    return messages


def logout_messages(root: Path) -> list[tuple[str, str]]:
    return [
        (logout_context(key), _text(text))
        for key, text in _load(root / LOGOUT_FILE).items()
    ]


def core_messages(root: Path) -> list[tuple[str, str]]:
    """Return every message of the ``core`` domain.

    Args:
        root: repository root.

    Returns:
        ``(msgctxt, msgid)`` pairs in source order.
    """
    return [
        *role_messages(root),
        *category_messages(root),
        *menu_messages(root),
        *logout_messages(root),
    ]


def _copy_working_tree(root: Path, target: Path) -> None:
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    for relative in filter(None, listing.split("\0")):
        source = root / relative
        if Path(relative).parts[0] == str(LOCALE_DIR) or not source.is_file():
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def docs_template(root: Path, jobs: int):
    """Return the template of the ``docs`` domain, built from a copy of the working tree.

    Args:
        root: repository root.
        jobs: parallel Sphinx processes.
    """
    with tempfile.TemporaryDirectory(prefix="infinito-i18n-docs-") as scratch:
        src = Path(scratch) / "src"
        pot = Path(scratch) / "docs.pot"
        _copy_working_tree(root, src)
        tooling = root / DOCS_TOOLING
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(tooling), str(root)]),
        }
        subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "infinito_docs.i18n",
                "--src",
                str(src),
                "--output",
                str(pot),
                "--jobs",
                str(jobs),
            ],
            check=True,
            env=env,
        )
        return read_catalog(pot)
