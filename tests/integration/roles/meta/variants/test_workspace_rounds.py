from __future__ import annotations

import copy
import functools
import ipaddress
import unittest
from collections.abc import Mapping

from utils.roles.applications.variants import (
    _resolve_round_include,
    services_overrides_for_round,
)

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")
SEMAPHORE = "web-app-semaphore"
INCUS = "svc-virt-incus"
PARTNERS = (
    SEMAPHORE,
    "web-app-openbao",
    "web-app-keycloak",
    "web-app-gitea",
    "web-svc-seaweedfs",
)
SMALLEST_TARGET_PREFIX = 30
ROUNDS = ((SEMAPHORE, 0), (INCUS, 0))


@functools.cache
def _overrides(primary: str, index: int) -> dict[str, dict]:
    return services_overrides_for_round(
        roles_dir=ROLES_DIR,
        round_index=index,
        primary_app_variants={primary: index},
    )


def _path(services: Mapping, *keys: str) -> object:
    node: object = services
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def _wide_ipv4(networks: object) -> bool:
    for network in networks if isinstance(networks, list) else []:
        try:
            parsed = ipaddress.ip_network(str(network), strict=False)
        except ValueError:
            continue
        if parsed.version == 4 and parsed.prefixlen <= SMALLEST_TARGET_PREFIX:
            return True
    return False


def round_findings(primary: str, overrides: Mapping[str, Mapping]) -> list[str]:
    """Args:
        primary: the primary app of the round.
        overrides: the round's merged services map per role.

    Returns:
        One message per partner or switch a workspace apply needs and the
        round lacks, empty when the round can run the workspace specs.
    """
    include = set(
        _resolve_round_include(primary_apps=[primary], services_overrides=overrides)
    )
    findings = [
        f"{primary}: the round deploys no {role}"
        for role in PARTNERS
        if role not in include
    ]
    semaphore = overrides.get(SEMAPHORE) or {}
    entry = _path(semaphore, "semaphore") or {}
    if "deploy" not in entry or "workspaces" not in entry:
        findings.append(f"{primary}: {SEMAPHORE} runs without deploy and workspaces")
    if _path(semaphore, "gitea", "enabled") is not True:
        findings.append(
            f"{primary}: {SEMAPHORE} runs without Gitea, so the deploy fixture "
            f"lists no platform host in workspaces.yml"
        )
    if not _wide_ipv4(_path(entry, "workspaces", "private_targets")):
        findings.append(
            f"{primary}: services.semaphore.workspaces.private_targets names no "
            f"IPv4 network of /{SMALLEST_TARGET_PREFIX} or wider"
        )
    if not _path(entry, "workspaces", "invite_client_id"):
        findings.append(
            f"{primary}: services.semaphore.workspaces.invite_client_id names no "
            f"store client, so the store specs of test-organizations.js skip"
        )
    keycloak = overrides.get("web-app-keycloak") or {}
    if _path(keycloak, "keycloak", "organizations", "enabled") is not True:
        findings.append(f"{primary}: Keycloak organizations are off")
    gitea = overrides.get("web-app-gitea") or {}
    if _path(gitea, "gitea", "workspaces", "enabled") is not True:
        findings.append(f"{primary}: the Gitea workspace organization is off")
    if primary == INCUS:
        incus = _path(overrides.get(INCUS) or {}, "incus") or {}
        if _path(incus, "api", "enabled") is not True:
            findings.append(f"{primary}: the Incus API is off")
        if not _path(incus, "api", "allowed_sources"):
            findings.append(f"{primary}: the Incus API admits no source")
        if _path(incus, "workspaces", "enabled") is not True:
            findings.append(f"{primary}: Incus workspaces are off")
    return findings


def _switched(
    overrides: Mapping[str, Mapping], role: str, keys: tuple[str, ...], value: object
) -> dict[str, dict]:
    """Args:
        overrides: a round's merged services map per role.
        role: the role whose services map changes.
        keys: the path below the services map that is set.
        value: what the path is set to.

    Returns:
        A deep copy of ``overrides`` with that one value replaced.
    """
    changed = copy.deepcopy(dict(overrides))
    node = changed[role]
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return changed


class TestWorkspaceRounds(unittest.TestCase):
    def test_each_workspace_round_deploys_every_partner_switched_on(self) -> None:
        for primary, index in ROUNDS:
            with self.subTest(primary=primary, round=index):
                self.assertEqual(
                    round_findings(primary, _overrides(primary, index)), []
                )

    def test_negative_control_semaphore_without_openbao_is_reported(self) -> None:
        overrides = _switched(
            _overrides(SEMAPHORE, 0),
            SEMAPHORE,
            ("openbao",),
            {"enabled": False, "shared": False},
        )
        self.assertIn(
            f"{SEMAPHORE}: the round deploys no web-app-openbao",
            round_findings(SEMAPHORE, overrides),
        )

    def test_negative_control_semaphore_without_the_platform_fixture_is_reported(
        self,
    ) -> None:
        for primary, index in ROUNDS:
            with self.subTest(primary=primary, round=index):
                overrides = _switched(
                    _overrides(primary, index),
                    SEMAPHORE,
                    ("gitea",),
                    {"enabled": False, "shared": False},
                )
                self.assertIn(
                    f"{primary}: {SEMAPHORE} runs without Gitea, so the deploy fixture "
                    f"lists no platform host in workspaces.yml",
                    round_findings(primary, overrides),
                )

    def test_negative_control_incus_without_semaphore_is_reported(self) -> None:
        overrides = _switched(
            _overrides(INCUS, 0),
            INCUS,
            ("semaphore",),
            {"enabled": False, "shared": False},
        )
        self.assertIn(
            f"{INCUS}: the round deploys no {SEMAPHORE}",
            round_findings(INCUS, overrides),
        )

    def test_negative_control_switches_left_off_are_reported(self) -> None:
        cases = (
            ("web-app-keycloak", ("keycloak", "organizations", "enabled"), False),
            ("web-app-gitea", ("gitea", "workspaces", "enabled"), False),
            (SEMAPHORE, ("semaphore", "workspaces", "private_targets"), []),
            (SEMAPHORE, ("semaphore", "workspaces", "invite_client_id"), None),
            (INCUS, ("incus", "api", "allowed_sources"), []),
        )
        for role, keys, value in cases:
            with self.subTest(role=role, path=".".join(keys)):
                overrides = _switched(_overrides(INCUS, 0), role, keys, value)
                self.assertEqual(len(round_findings(INCUS, overrides)), 1)


if __name__ == "__main__":
    unittest.main()
