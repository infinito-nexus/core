"""Integration guard: an onion round deploys no partner in a variant that drops
the onion.

``test_clearnet_role_forbids_variant_tor`` refuses a variant that pins the onion
on while binding a role whose ``meta/services.yml`` pins ``tor.enabled`` to a
literal false. A partner can also refuse the onion only in some of its
variants, and which variant a partner runs in is decided by the round, not by
the variant that binds it: a round hands every partner its round index, clamped
or moved by a ``# variant-pin:``. ``web-app-discourse#1`` pinned the onion on
and bound ``web-app-matrix``, whose round variant ``#1`` drops it for jitsi;
the deploy's domain map then refused matrix on the tor node, hours into the CI
row.

For every round the CI matrix plans (each role as the only primary, in each of
its variants) the guard settles the round with
:func:`utils.roles.applications.variants.resolve_round` and requires that,
when the primary runs with the onion on, no frontend partner in the round's
include runs a variant whose merged services map pins ``tor.enabled: false``.
Partners whose own ``meta/services.yml`` already pins the onion off belong to
the sister rule and are left to it.

Suppression (see ``docs/contributing/actions/testing/suppression.md``): the
sister rule's ``# nocheck: clearnet-variant-tor`` in the primary role's
``meta/variants.yml``, naming why the pairing is sound.
"""

from __future__ import annotations

import functools
import textwrap
import unittest
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import yaml

from cli.meta.roles.applications.resolution.combined import repo_paths
from utils.annotations.suppress import line_has_rule
from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.services.registry import detect_service_channel
from utils.roles.applications.variants import VariantPinError, resolve_round
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")
RULE = "clearnet-variant-tor"

HOST = "web-app-onion-host"
PARTNER = "web-app-onion-partner"


def _yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return load_yaml_str(read_text(str(path)))
    except yaml.YAMLError:
        return None


def _tor(services: Any) -> Any:
    entry = services.get("tor") if isinstance(services, Mapping) else None
    return entry.get("enabled") if isinstance(entry, Mapping) else None


def _onion_on(value: Any) -> bool:
    return value is True or (isinstance(value, str) and "in group_names" in value)


def _base_refuses_onion(role: str, roles_dir: str) -> bool:
    return _tor(_yaml(Path(roles_dir) / role / ROLE_FILE_META_SERVICES)) is False


def _suppressed(role: str, roles_dir: str) -> bool:
    path = Path(roles_dir) / role / ROLE_FILE_META_VARIANTS
    return path.is_file() and any(
        line_has_rule(line, RULE) for line in read_text(str(path)).splitlines()
    )


def _sweep(roles_dir: str) -> list[str]:
    """Every onion round of *roles_dir* that deploys a partner off the onion.

    Args:
        roles_dir: the roles tree.

    Returns:
        One finding per (round, partner); rounds whose pins never settle are
        left to ``test_variant_pin_fixed_point``.
    """
    variants = get_variants(roles_dir=roles_dir, readonly=True)
    findings: list[str] = []
    for app, variant_list in sorted(variants.items()):
        if _suppressed(app, roles_dir):
            continue
        for index in range(len(variant_list)):
            try:
                resolved = resolve_round(
                    roles_dir=roles_dir,
                    round_index=index,
                    primary_app_variants={app: index},
                    variants_per_app=variants,
                )
            except VariantPinError:
                continue
            if not _onion_on(_tor(resolved.services_overrides.get(app))):
                continue
            for partner in resolved.include:
                if partner == app or detect_service_channel(partner) != "frontend":
                    continue
                if partner not in resolved.services_overrides:
                    continue
                if _base_refuses_onion(partner, roles_dir):
                    continue
                if _tor(resolved.services_overrides[partner]) is False:
                    findings.append(
                        f"{app}#{index} runs on the onion but deploys {partner} "
                        f"in its variant #{resolved.active_index[partner]}, "
                        "which pins tor.enabled false"
                    )
    return findings


@functools.cache
def _repo_sweep() -> tuple[str, ...]:
    return tuple(_sweep(ROLES_DIR))


def _role(role: str, *, services: str, variants: str) -> dict[str, str]:
    """The files of one fixture role.

    Args:
        role: the role name; its entity is the name without ``web-app-``.
        services: entries appended to the role's ``meta/services.yml``.
        variants: the body of the role's ``meta/variants.yml``.
    """
    entity = role.removeprefix("web-app-")
    return {
        f"{role}/{ROLE_FILE_VARS_MAIN}": f"application_id: {role}\n",
        f"{role}/{ROLE_FILE_META_SERVICES}": f"{entity}:\n  image: {entity}\n"
        + textwrap.dedent(services),
        f"{role}/{ROLE_FILE_META_VARIANTS}": textwrap.dedent(variants),
    }


_DYNAMIC_TOR = """\
    tor:
      enabled: "{{ 'svc-net-tor' in group_names }}"
    """


def _tree(*, partner_round_tor: bool, host_marker: str = "") -> dict[str, str]:
    """HOST#0 pins the onion on and depends on PARTNER, whose variant 0 is
    the one round 0 hands it.

    Args:
        partner_round_tor: the tor pin of PARTNER's variant 0.
        host_marker: a line prepended to HOST's ``meta/variants.yml``.
    """
    return {
        f"{HOST}/{ROLE_FILE_META_MAIN}": f"dependencies:\n  - {PARTNER}\n",
        **_role(
            HOST,
            services=_DYNAMIC_TOR,
            variants=host_marker
            + """\
                - services:
                    tor:
                      enabled: true
                """,
        ),
        **_role(
            PARTNER,
            services=_DYNAMIC_TOR,
            variants=f"""\
                - services:
                    tor:
                      enabled: {str(partner_round_tor).lower()}
                - services:
                    tor:
                      enabled: true
                """,
        ),
    }


class TestOnionRoundPartnerTor(unittest.TestCase):
    def test_no_onion_round_deploys_a_partner_variant_off_the_onion(self) -> None:
        findings = _repo_sweep()
        if findings:
            self.fail(
                f"{len(findings)} onion round(s) deploy a partner in a variant "
                "that drops the onion, so the deploy's domain map refuses that "
                "partner on the tor node:\n"
                + "\n".join(f"  - {finding}" for finding in findings)
                + "\n\nMove the partner into a variant of this role whose round "
                "index hands it an onion variant, turn the onion off for this "
                f"variant, or suppress with '# nocheck: {RULE}' naming why the "
                "pairing is sound."
            )


class TestOnionRoundPartnerTorControls(unittest.TestCase):
    def _sweep_tree(self, files: Mapping[str, str]) -> list[str]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        roles = Path(tmp.name) / "roles"
        for relative, body in files.items():
            path = roles / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        resolver_root = patch.object(repo_paths, "PROJECT_ROOT", Path(tmp.name))
        resolver_root.start()
        self.addCleanup(resolver_root.stop)
        return _sweep(str(roles))

    def test_a_partner_round_variant_off_the_onion_is_reported(self) -> None:
        self.assertEqual(
            self._sweep_tree(_tree(partner_round_tor=False)),
            [
                (
                    f"{HOST}#0 runs on the onion but deploys {PARTNER} in its "
                    "variant #0, which pins tor.enabled false"
                )
            ],
        )

    def test_a_partner_round_variant_on_the_onion_passes(self) -> None:
        self.assertEqual(self._sweep_tree(_tree(partner_round_tor=True)), [])

    def test_the_marker_suppresses_the_primary(self) -> None:
        tree = _tree(
            partner_round_tor=False,
            host_marker=f"# nocheck: {RULE} fixture pairing\n",
        )
        self.assertEqual(self._sweep_tree(tree), [])


if __name__ == "__main__":
    unittest.main()
