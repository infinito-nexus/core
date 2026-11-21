"""Lint: a bridged addon never activates while a bridged partner is off.

A ``meta/addons/<id>.yml`` with a non-empty ``bridges:`` list is either
``required: false`` and disabled by default (``enabled: false``), or its
``enabled`` expression names ``services.<target>.enabled`` for every bridged
target. An addon that works with any one of several partners joins their flags
with ``or``.

Suppression: ``# nocheck: addon-partner-gate <reason>`` in the head of the addon
file; the reason is mandatory.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head, marker_reason
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

from . import PROJECT_ROOT

RULE = "addon-partner-gate"


def _reason(lines: list[str]) -> str | None:
    if not is_suppressed_in_head(lines, RULE):
        return None
    return next(
        (reason for line in lines if (reason := marker_reason(line, RULE)) is not None),
        "",
    )


def partner_gate_problems(roles_dir: Path) -> list[str]:
    """Returns one line per bridged addon that can activate without its partner.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    problems: list[str] = []
    for addon_file in sorted(roles_dir.glob(f"*/{ROLE_DIR_META_ADDONS}/*.yml")):
        role = addon_file.relative_to(roles_dir).parts[0]
        where = f"{role}: {ROLE_DIR_META_ADDONS}/{addon_file.name}"
        spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
        bridges = spec.get("bridges") if isinstance(spec, Mapping) else None
        if not isinstance(bridges, list) or not bridges:
            continue
        reason = _reason(read_text(str(addon_file)).splitlines())
        if reason is not None:
            if not reason.strip():
                problems.append(f"{where} carries # nocheck: {RULE} without a reason")
            continue
        required = bool(spec.get("required", False))
        enabled = spec.get("enabled", required)
        if not required and enabled is False:
            continue
        ungated = [
            target
            for target in bridges
            if f"services.{target}.enabled" not in str(enabled)
        ]
        if ungated:
            kind = "required" if required else "optional and not disabled by default"
            problems.append(
                f"{where} is {kind}, but its enabled ({enabled!r}) names no "
                + ", ".join(f"services.{target}.enabled" for target in ungated)
            )
    return problems


def _addon(roles_dir: Path, role: str, name: str, content: str) -> None:
    path = roles_dir / role / ROLE_DIR_META_ADDONS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestAddonsPartnerGate(unittest.TestCase):
    def test_every_bridged_addon_is_gated_on_its_partners(self) -> None:
        problems = partner_gate_problems(PROJECT_ROOT / "roles")
        self.assertEqual(
            [],
            problems,
            f"bridged addon(s) that can activate without a partner ({len(problems)}):\n  "
            + "\n  ".join(problems),
        )

    def test_the_rule_reports_each_way_to_skip_a_partner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _addon(
                roles_dir, "web-app-a", "always.yml", "required: true\nbridges: [sso]\n"
            )
            _addon(
                roles_dir,
                "web-app-a",
                "other_key.yml",
                "enabled: \"{{ lookup('config', 'web-app-a', 'services.a.login.method.sso.enabled') }}\"\n"
                "required: false\nbridges: [sso]\n",
            )
            _addon(
                roles_dir,
                "web-app-a",
                "half.yml",
                "enabled: \"{{ lookup('config', 'web-app-a', 'services.talk.enabled') }}\"\n"
                "required: true\nbridges: [talk, coturn]\n",
            )
            _addon(
                roles_dir,
                "web-app-a",
                "bare.yml",
                "# nocheck: addon-partner-gate\nrequired: true\nbridges: [sso]\n",
            )
            _addon(
                roles_dir,
                "web-app-a",
                "off.yml",
                "enabled: false\nrequired: false\nbridges: [sso]\n",
            )
            _addon(
                roles_dir,
                "web-app-a",
                "any.yml",
                "enabled: \"{{ x('services.a.enabled') or x('services.b.enabled') }}\"\n"
                "required: true\nbridges: [a, b]\n",
            )
            _addon(
                roles_dir,
                "web-app-a",
                "exempt.yml",
                "# nocheck: addon-partner-gate  federates with every server\nrequired: false\nbridges: [sso]\n",
            )

            problems = partner_gate_problems(roles_dir)

        self.assertEqual(4, len(problems), problems)
        self.assertTrue(any("always.yml is required" in p for p in problems))
        self.assertTrue(any("other_key.yml is optional" in p for p in problems))
        self.assertTrue(
            any(
                "half.yml" in p
                and "services.coturn.enabled" in p
                and "talk" not in p.split("names no")[1]
                for p in problems
            )
        )
        self.assertTrue(any("bare.yml carries" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
