"""Lint: a role's network reachability is declared once, and narrowing it says why.

``meta/networks.yml`` ``reachability`` decides which networks a role is served
on: ``modes`` lists them (empty or absent means every network) and
``single_mode`` keeps the role under one domain. The Tor service entry in
``meta/services.yml`` stays the dependency edge only, so ``exclusive`` and
``primary`` there would be a second source for the same decision.

A ``single_mode: true`` or a ``modes`` list below every network carries
``# nocheck: network-reachability`` plus a reason, on or directly above that
line, so the next reader learns why the role is not served everywhere before
widening it.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import NETWORKS, role_reachability
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
RETIRED_TOR_KEYS = ("exclusive", "primary")
REACHABILITY_KEYS = frozenset({"modes", "single_mode"})
_RULE = "network-reachability"
_MIN_REASON_CHARS = 10

_MARKER_RE = re.compile(
    r"(?:noqa|nocheck)\s*:\s*"
    r"(?:[a-z0-9][a-z0-9\-]*)(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*(.*)$",
    re.IGNORECASE,
)


def _load(path) -> dict:
    data = load_yaml_any(str(path), default_if_missing={}) or {}
    return data if isinstance(data, dict) else {}


def _reachability_key_line(lines: list[str], key: str) -> int | None:
    """The 1-based line declaring ``reachability.<key>``, or None."""
    inside = False
    for number, line in enumerate(lines, 1):
        if line and not line[0].isspace():
            inside = line.startswith("reachability:")
            continue
        if inside and line.strip().startswith(f"{key}:"):
            return number
    return None


def _reason_for(lines: list[str], line_no: int) -> str | None:
    """The suppression reason governing *line_no*, or None when unsuppressed."""
    candidates = [line_no - 1]
    previous = line_no - 2
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    candidates.append(previous)
    for index in candidates:
        if index < 0 or not line_has_rule(lines[index], _RULE):
            continue
        match = _MARKER_RE.search(lines[index])
        return match.group(1).strip().lstrip("-:").strip() if match else ""
    return None


class TestNetworkReachability(unittest.TestCase):
    def test_reachability_is_valid_and_narrowing_carries_a_reason(self) -> None:
        problems: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            path = role_dir / ROLE_FILE_META_NETWORKS
            networks = _load(path)
            reach = networks.get("reachability")
            if reach is None:
                continue
            try:
                modes, single_mode = role_reachability(
                    {"networks": networks}, app=role_dir.name
                )
            except (TypeError, ValueError) as exc:
                problems.append(str(exc))
                continue
            problems.extend(
                f"{role_dir.name}: {ROLE_FILE_META_NETWORKS} reachability.{key} "
                f"is unknown; known: {', '.join(sorted(REACHABILITY_KEYS))}"
                for key in sorted(set(reach) - REACHABILITY_KEYS)
            )
            lines = read_text(str(path)).splitlines()
            restricted = bool(modes) and set(modes) != set(NETWORKS)
            for key, narrows in (("single_mode", single_mode), ("modes", restricted)):
                if not narrows:
                    continue
                line_no = _reachability_key_line(lines, key)
                reason = _reason_for(lines, line_no) if line_no else None
                if reason is None:
                    problems.append(
                        f"{role_dir.name}: {ROLE_FILE_META_NETWORKS} reachability."
                        f"{key} narrows the networks but carries no "
                        f"`# nocheck: {_RULE}` with a reason on or above it"
                    )
                elif len(reason) < _MIN_REASON_CHARS:
                    problems.append(
                        f"{role_dir.name}: {ROLE_FILE_META_NETWORKS} reachability."
                        f"{key}: `# nocheck: {_RULE}` states no reason"
                    )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_tor_service_carries_no_reachability_keys(self) -> None:
        problems: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            tor = _load(role_dir / ROLE_FILE_META_SERVICES).get("tor")
            if not isinstance(tor, dict):
                continue
            problems.extend(
                f"{role_dir.name}: {ROLE_FILE_META_SERVICES} tor.{key} "
                f"belongs in {ROLE_FILE_META_NETWORKS} reachability"
                for key in RETIRED_TOR_KEYS
                if key in tor
            )
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
