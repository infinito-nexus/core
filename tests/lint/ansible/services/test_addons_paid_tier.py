"""Lint: an integration behind a commercial tier is opt-in and documented.

An addon whose ``config.tier`` (or another ``config.*_tier`` key) names a
commercial tier (``paid``, ``enterprise``) is a paid edge of the integration
matrix. It MUST stay off by default (``enabled`` absent or the literal
``false``), MUST NOT be ``required: true``, and the role's ``README.md`` MUST
carry a line naming both the addon id and the tier, so an operator learns what
licence switching it on takes.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

from . import PROJECT_ROOT

COMMERCIAL_TIERS: frozenset[str] = frozenset({"paid", "enterprise"})


def _tier(spec: Mapping) -> str | None:
    config = spec.get("config")
    if not isinstance(config, Mapping):
        return None
    return next(
        (
            str(value).lower()
            for key, value in config.items()
            if (key == "tier" or str(key).endswith("_tier"))
            and str(value).lower() in COMMERCIAL_TIERS
        ),
        None,
    )


def paid_tier_problems(roles_dir: Path) -> list[str]:
    """Return one line per commercial-tier addon that is not opt-in and documented.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    problems: list[str] = []
    for addon_file in sorted(roles_dir.glob(f"*/{ROLE_DIR_META_ADDONS}/*.yml")):
        spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
        tier = _tier(spec) if isinstance(spec, Mapping) else None
        if tier is None:
            continue
        role = addon_file.relative_to(roles_dir).parts[0]
        addon_id = addon_file.stem
        where = f"{role}: {ROLE_DIR_META_ADDONS}/{addon_file.name} ({tier} tier)"
        if spec.get("enabled", False) is not False:
            problems.append(
                f"{where} is enabled by {spec.get('enabled')!r}; a paid edge "
                "stays off until the operator opts in"
            )
        if spec.get("required") is True:
            problems.append(f"{where} is required: true; a paid edge is optional")
        readme = roles_dir / role / "README.md"
        lines = read_text(str(readme)).splitlines() if readme.is_file() else []
        if not any(addon_id in line and tier in line.lower() for line in lines):
            problems.append(
                f"{where}: {role}/README.md has no line naming both "
                f"{addon_id!r} and the {tier} tier"
            )
    return problems


def _role(roles_dir: Path, role: str, addons: dict, readme: str) -> None:
    for name, content in addons.items():
        path = roles_dir / role / ROLE_DIR_META_ADDONS / f"{name}.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (roles_dir / role / "README.md").write_text(readme, encoding="utf-8")


class TestAddonsPaidTier(unittest.TestCase):
    def test_every_paid_edge_is_opt_in_and_documented(self) -> None:
        problems = paid_tier_problems(PROJECT_ROOT / "roles")
        self.assertEqual(
            [],
            problems,
            f"commercial-tier addon(s) breaking the paid contract ({len(problems)}):\n  "
            + "\n  ".join(problems),
        )

    def test_the_rule_reports_each_way_to_break_a_paid_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(
                roles_dir,
                "web-app-a",
                {
                    "ok": "enabled: false\nconfig:\n  tier: paid\n",
                    "licence": "config:\n  licence_tier: Enterprise\n",
                    "free": "enabled: true\nconfig:\n  tier: community\n",
                    "on": "enabled: true\nconfig:\n  tier: paid\n",
                    "core": "required: true\nconfig:\n  tier: paid\n",
                    "silent": "enabled: false\nconfig:\n  tier: enterprise\n",
                },
                "`ok` needs the paid store.\n"
                "`licence` is an Enterprise feature.\n"
                "`on` is paid.\n`core` is paid.\n`silent` exists.\n",
            )

            problems = paid_tier_problems(roles_dir)

        self.assertEqual(3, len(problems), problems)
        self.assertTrue(any("on.yml" in p and "enabled" in p for p in problems))
        self.assertTrue(any("core.yml" in p and "required" in p for p in problems))
        self.assertTrue(any("silent.yml" in p and "README" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
