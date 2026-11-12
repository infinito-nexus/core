"""Lint guard: a role image that pip-installs core runs a Python core supports.

pip refuses ``infinito-nexus`` on a base outside ``requires-python`` of
pyproject.toml. The image updater bumped ``web-app-docs`` to
``python:3.15-slim`` that way (PR 1448) and broke every deploy with docs.
``follow: requires-python`` holds the updater inside the range; this guard
makes every such role declare it and pin a base inside the range.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.requires_python import FOLLOW, requires_python, supported_minors
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import version_key

from . import PROJECT_ROOT

_INSTALLS_CORE = re.compile(r"infinito-nexus(\[[^\]]*\])? @ git\+")


def _entities(role):
    data = load_yaml_any(str(role / ROLE_FILE_META_SERVICES), default_if_missing={})
    return {
        name: entity
        for name, entity in (data or {}).items()
        if isinstance(entity, dict)
    }


def _roles_installing_core():
    return sorted(
        {
            path.relative_to(PROJECT_ROOT / "roles").parts[0]
            for path in (PROJECT_ROOT / "roles").glob("*/*/Dockerfile*")
            if path.is_file() and _INSTALLS_CORE.search(read_text(str(path)))
        }
    )


class TestRequiresPythonFollowers(unittest.TestCase):
    def test_every_role_installing_core_follows_requires_python(self) -> None:
        roles = _roles_installing_core()
        self.assertIn("web-app-docs", roles)
        missing = [
            role
            for role in roles
            if not any(
                entity.get("follow") == FOLLOW
                for entity in _entities(PROJECT_ROOT / "roles" / role).values()
            )
        ]
        self.assertEqual(
            missing,
            [],
            f"these roles pip-install infinito-nexus into their image but no "
            f"entity of meta/services.yml sets 'follow: {FOLLOW}', so the image "
            f"updater may move the base past requires-python",
        )

    def test_every_follower_pins_a_supported_python(self) -> None:
        minors = supported_minors(requires_python(PROJECT_ROOT))
        followers = {
            f"{role.name}/{name}": str(entity.get("version"))
            for role in sorted((PROJECT_ROOT / "roles").iterdir())
            for name, entity in _entities(role).items()
            if entity.get("follow") == FOLLOW
        }
        self.assertIn("web-app-docs/docs", followers)
        outside = {
            key: version
            for key, version in followers.items()
            if version_key(version)[0] != 3 or version_key(version)[1] not in minors
        }
        self.assertEqual(
            outside,
            {},
            f"these pins lie outside requires-python of pyproject.toml "
            f"(Python 3.{minors.start} to 3.{minors.stop - 1}); pip refuses to "
            f"install infinito-nexus there",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
