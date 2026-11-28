"""Lint: a deliberately skipped integration is a disabled addon with a reason.

The upstream plugin survey records an integration it decides against as a
``meta/addons/<id>.yml`` carrying ``skipped: <reason>``. Such an addon

* states its reason as a non-blank string,
* stays off: ``enabled`` is absent or the literal ``false``,
* is never ``required: true``,
* declares no ``bridges:``, because a skipped integration wires nothing.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

from . import PROJECT_ROOT


def skipped_problems(roles_dir: Path) -> list[str]:
    """Return one line per skipped addon that breaks the skipped contract.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    problems: list[str] = []
    for addon_file in sorted(roles_dir.glob(f"*/{ROLE_DIR_META_ADDONS}/*.yml")):
        spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
        if not isinstance(spec, Mapping) or "skipped" not in spec:
            continue
        role = addon_file.relative_to(roles_dir).parts[0]
        where = f"{role}: {ROLE_DIR_META_ADDONS}/{addon_file.name}"
        reason = spec["skipped"]
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"{where} skipped MUST state its reason, got {reason!r}")
        if spec.get("enabled", False) is not False:
            problems.append(
                f"{where} is skipped but enabled is {spec.get('enabled')!r}, "
                "expected the literal false"
            )
        if spec.get("required") is True:
            problems.append(f"{where} is skipped but required: true")
        if "bridges" in spec:
            problems.append(
                f"{where} is skipped but declares bridges; a skipped "
                "integration wires nothing"
            )
    return problems


def _addon(roles_dir: Path, name: str, content: str) -> None:
    path = roles_dir / "web-app-a" / ROLE_DIR_META_ADDONS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestAddonsSkipped(unittest.TestCase):
    def test_every_skipped_addon_is_disabled_with_a_reason(self) -> None:
        problems = skipped_problems(PROJECT_ROOT / "roles")
        self.assertEqual(
            [],
            problems,
            f"skipped addon(s) breaking the contract ({len(problems)}):\n  "
            + "\n  ".join(problems),
        )

    def test_the_rule_reports_each_broken_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _addon(roles_dir, "ok.yml", "enabled: false\nskipped: upstream is EOL\n")
            _addon(roles_dir, "implicit.yml", "skipped: no stable release\n")
            _addon(roles_dir, "plain.yml", "enabled: false\n")
            _addon(roles_dir, "blank.yml", "enabled: false\nskipped: '  '\n")
            _addon(roles_dir, "flag.yml", "enabled: false\nskipped: true\n")
            _addon(roles_dir, "on.yml", "enabled: true\nskipped: paid only\n")
            _addon(
                roles_dir,
                "dynamic.yml",
                "enabled: \"{{ x('services.a.enabled') }}\"\nskipped: paid only\n",
            )
            _addon(roles_dir, "core.yml", "required: true\nskipped: paid only\n")
            _addon(
                roles_dir,
                "wired.yml",
                "enabled: false\nskipped: paid only\nbridges: [a]\n",
            )

            problems = skipped_problems(roles_dir)

        self.assertEqual(6, len(problems), problems)
        for name in ("blank", "flag", "on", "dynamic", "core", "wired"):
            self.assertTrue(any(f"/{name}.yml" in p for p in problems), name)


if __name__ == "__main__":
    unittest.main()
