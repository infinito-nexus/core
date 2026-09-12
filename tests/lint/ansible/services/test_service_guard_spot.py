"""Lint: a compose service block is switched by its own services entry.

``meta/services.yml`` is the single place that says whether a service is part
of a deployment. A ``compose.yml.j2`` that wraps a service key in
``{% if <VAR> | bool %}`` therefore has to reach that entry, or the template
and the declaration become two switches for one container and drift apart:
the resource model, the README graph and the network layer read the entry
while the container follows something else.

The reference is not required on the guard itself. A role may name the
condition once in ``vars/`` and reuse it, so the chain is followed through
every variable the guard mentions, and one link in it must resolve the state
through ``lookup('config', …, 'services.<key>.enabled')``.

The chain also runs through config: a value that reads another topic is
followed into the resolved application config and on from there. Nextcloud
reaches its Talk entry that way, over ``addons.spreed.enabled``, and a
resolver that stopped at the role's variables would call that a bypass.

Scope
-----

Only guards indented by at most two spaces are checked. That is the
indentation of a compose service key, so a deeper guard selects content
inside a service (a network, an environment line) rather than the service
itself, and its state is the surrounding block's business.

Variables are resolved from the role's own ``vars/`` and ``defaults/``. A
guard whose variable is built somewhere else, a ``set_fact`` for instance,
cannot be followed here and needs the suppression.

Suppression
-----------

``# nocheck: service-guard-spot`` on the guard line in the template.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "service-guard-spot"

ROLES_DIR = PROJECT_ROOT / "roles"

_TEMPLATE_REL = "templates/compose.yml.j2"  # nocheck: role-file-spot
_VAR_DIRS = ("vars", "defaults")
_SERVICE_KEY_INDENT = 2

_GUARD_RE = re.compile(r"^(\s*)\{%-?\s*if\s+([A-Z][A-Z0-9_]*)\s*\|\s*bool\s*-?%\}")
_DEFINITION_RE = re.compile(r"^([A-Z][A-Z0-9_]*):\s*(.*)$")
_REFERENCE_RE = re.compile(r"[A-Z][A-Z0-9_]{2,}")
_CONFIG_PATH_RE = re.compile(
    r"lookup\(\s*['\"]config['\"]\s*,[^,]+,\s*['\"]([A-Za-z0-9_.\-]+)['\"]"
)
_SPOT_RE = re.compile(r"^services\.[A-Za-z0-9_.\-]+\.enabled$")


def _definitions(role_dir: Path) -> dict[str, str]:
    """Return ``{VAR: raw definition}`` for one role's variable files.

    Args:
        role_dir: the role directory to scan.
    """
    definitions: dict[str, str] = {}
    for var_dir in _VAR_DIRS:
        for path in sorted((role_dir / var_dir).glob("*.yml")):
            for line in read_text(str(path)).splitlines():
                match = _DEFINITION_RE.match(line)
                if match:
                    definitions[match.group(1)] = match.group(2)
    return definitions


def _config_value(config: Mapping, path: str) -> str:
    """Return the raw value at a dotted config path, or "" when absent.

    Args:
        config: the role's resolved application config.
        path: a dotted path such as ``addons.spreed.enabled``.
    """
    value: object = config
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return ""
        value = value[part]
    return str(value)


def _reaches_the_spot(var: str, definitions: dict[str, str], config: Mapping) -> bool:
    """Return whether ``var``'s definition chain reads a services entry.

    Args:
        var: the variable named by the guard.
        definitions: the role's ``{VAR: raw definition}`` mapping.
        config: the role's resolved application config, for config hops.
    """
    seen: set[str] = set()
    pending = [definitions.get(var, "")]
    while pending:
        definition = pending.pop()
        for path in _CONFIG_PATH_RE.findall(definition):
            if _SPOT_RE.match(path):
                return True
            if path in seen:
                continue
            seen.add(path)
            pending.append(_config_value(config, path))
        for name in _REFERENCE_RE.findall(definition):
            if name in seen:
                continue
            seen.add(name)
            pending.append(definitions.get(name, ""))
    return False


def offenders() -> list[str]:
    """Return one finding per service guard that bypasses its services entry."""
    findings: list[str] = []
    defaults = get_application_defaults(roles_dir=ROLES_DIR)
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        template = role_dir / _TEMPLATE_REL
        if not template.is_file():
            continue
        definitions = _definitions(role_dir)
        config = defaults.get(role_dir.name) or {}
        for line_no, line in enumerate(read_text(str(template)).splitlines(), start=1):
            guard = _GUARD_RE.match(line)
            if not guard or len(guard.group(1)) > _SERVICE_KEY_INDENT:
                continue
            if line_has_rule(line, _RULE):
                continue
            var = guard.group(2)
            if _reaches_the_spot(var, definitions, config):
                continue
            findings.append(
                f"{role_dir.name}: {_TEMPLATE_REL}:{line_no} switches a service "
                f"block on `{var}`, whose definition chain never reads "
                f"`lookup('config', …, 'services.<key>.enabled')`. Point one link "
                f"of the chain at the service's own entry, or mark the guard "
                f"with `# nocheck: {_RULE}`."
            )
    return findings


class TestServiceGuardSpot(unittest.TestCase):
    def test_every_service_guard_reads_its_services_entry(self) -> None:
        findings = offenders()
        self.assertEqual(
            [],
            findings,
            f"service guard(s) bypassing meta/services.yml ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_finds_service_guards(self) -> None:
        seen = 0
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            template = role_dir / _TEMPLATE_REL
            if not template.is_file():
                continue
            for line in read_text(str(template)).splitlines():
                guard = _GUARD_RE.match(line)
                if guard and len(guard.group(1)) <= _SERVICE_KEY_INDENT:
                    seen += 1
        self.assertTrue(
            seen,
            "no compose template guards a service block, so the rule would pass "
            "vacuously; check that the guard shape still matches",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
