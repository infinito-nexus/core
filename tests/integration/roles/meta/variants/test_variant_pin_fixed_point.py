"""Integration guard: every matrix round settles its variant pins, and no pin
in force stands above a service entry the round switches off.

A ``# variant-pin:`` in ``R#i`` is in force only while ``R`` is in the round's
include running variant ``i``, and the include can depend on the variant a pin
moves a partner into. :func:`utils.roles.applications.variants.resolve_round`
therefore recomputes the include and the pins in force from the clamped
indices until the assignment reproduces itself. For every round the CI matrix
plans (each role as the only primary, in each of its variants) the guard
requires:

- ``resolve_round`` raises no ``VariantPinError``: no pins oscillate,
  conflict, or name a ``#reciprocal`` the partner cannot resolve;
- no pin in force stands above a service entry the carrier runs with
  ``enabled: false`` in the settled round's services map, such as the guide
  host every non-primary role has switched off. That pin moves its partner
  for a dependency the round never deploys.

At least one round must move a partner off its clamped index, or the guard
checks a mechanism nothing exercises.
"""

from __future__ import annotations

import functools
import textwrap
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from unittest.mock import patch

from cli.meta.roles.applications.resolution.combined import repo_paths
from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.roles.applications.variant_pins import (
    PIN,
    VariantPinError,
    _service_key_lines,
)
from utils.roles.applications.variants import clamped_assignment, resolve_round
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from utils.roles.applications.variants import ResolvedRound

ROLES_DIR = str(PROJECT_ROOT / "roles")

HOST = "web-app-pin-host"
LEFT = "web-app-pin-left"
RIGHT = "web-app-pin-right"


@dataclass(frozen=True)
class Sweep:
    """What the guard finds across every round one roles tree plans.

    Attributes:
        unsettled: round -> why its pins never settle.
        dead_pins: ``(round, pin)`` per pin in force above a disabled entry.
        moving: the rounds in which a pin moves a partner off its clamped index.
    """

    unsettled: dict[str, str]
    dead_pins: tuple[tuple[str, str], ...]
    moving: tuple[str, ...]


def _pinned_keys(role: str, roles_dir: str) -> dict[int, dict[str, str]]:
    """Map variant index -> {pinned partner: the service key the pin stands above}.

    Args:
        role: the role whose ``meta/variants.yml`` is read.
        roles_dir: the roles tree.
    """
    path = Path(roles_dir) / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return {}
    text = read_text(str(path))
    lines = text.splitlines()
    found: dict[int, dict[str, str]] = {}
    for index, keys in _service_key_lines(text).items():
        for key, line_no in keys.items():
            match = PIN.search(lines[line_no - 1]) if line_no else None
            if match:
                found.setdefault(index, {})[match.group(1)] = key
    return found


def _dead_pins(resolved: ResolvedRound, roles_dir: str) -> list[str]:
    """The pins in force above a service entry the round runs disabled.

    Args:
        resolved: the settled round.
        roles_dir: the roles tree the pins are read from.
    """
    dead: list[str] = []
    for carrier in resolved.include:
        if carrier not in resolved.active_index:
            continue
        services = resolved.services_overrides.get(carrier)
        if not isinstance(services, Mapping):
            continue
        index = resolved.active_index[carrier]
        pinned = _pinned_keys(carrier, roles_dir).get(index, {})
        for partner, key in sorted(pinned.items()):
            entry = services.get(key)
            if isinstance(entry, Mapping) and entry.get("enabled") is False:
                dead.append(
                    f"{carrier}#{index} pins {partner} above services.{key}, "
                    "which the round runs with enabled: false"
                )
    return dead


def _sweep(roles_dir: str) -> Sweep:
    """Settle every round the matrix plans for *roles_dir* and judge its pins.

    Args:
        roles_dir: the roles tree.
    """
    variants = get_variants(roles_dir=roles_dir, readonly=True)
    unsettled: dict[str, str] = {}
    dead_pins: list[tuple[str, str]] = []
    moving: list[str] = []
    for app, variant_list in sorted(variants.items()):
        for index in range(len(variant_list)):
            label = f"{app}#{index}"
            primaries = {app: index}
            try:
                resolved = resolve_round(
                    roles_dir=roles_dir,
                    round_index=index,
                    primary_app_variants=primaries,
                    variants_per_app=variants,
                )
            except VariantPinError as exc:
                unsettled[label] = str(exc)
                continue
            clamped = clamped_assignment(
                round_index=index,
                primary_app_variants=primaries,
                variants_per_app=variants,
            )
            if resolved.active_index != clamped:
                moving.append(label)
            dead_pins.extend((label, pin) for pin in _dead_pins(resolved, roles_dir))
    return Sweep(unsettled, tuple(dead_pins), tuple(moving))


@functools.cache
def _repo_sweep() -> Sweep:
    return _sweep(ROLES_DIR)


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


def _oscillating_pair() -> dict[str, str]:
    """A tree whose ``HOST#0`` round never settles.

    Returns:
        The files of HOST, which depends on LEFT and RIGHT; LEFT#0 pins
        RIGHT#1 and RIGHT#1 pins LEFT#1, whose own entry carries no pin.
    """
    return {
        f"{HOST}/{ROLE_FILE_META_MAIN}": f"dependencies:\n  - {LEFT}\n  - {RIGHT}\n",
        **_role(HOST, services="", variants="- {}\n"),
        **_role(
            LEFT,
            services="",
            variants=f"""\
                - services:
                    # variant-pin: {RIGHT}#1
                    pin-right:
                      enabled: true
                - {{}}
                """,
        ),
        **_role(
            RIGHT,
            services="",
            variants=f"""\
                - {{}}
                - services:
                    # variant-pin: {LEFT}#1
                    pin-left:
                      enabled: true
                """,
        ),
    }


def _pin_above_disabled_entry() -> dict[str, str]:
    """A tree whose ``HOST#0`` round settles on a pin above a disabled entry.

    Returns:
        The files of HOST, whose variant 0 pins RIGHT#1 above a
        ``pin-right`` entry it switches off, and of RIGHT.
    """
    return {
        **_role(
            HOST,
            services="""\
                pin-right:
                  enabled: true
                  shared: true
                """,
            variants=f"""\
                - services:
                    # variant-pin: {RIGHT}#1
                    pin-right:
                      enabled: false
                      shared: false
                """,
        ),
        **_role(RIGHT, services="", variants="- {}\n- {}\n"),
    }


class TestVariantPinFixedPoint(unittest.TestCase):
    def test_every_round_settles(self) -> None:
        unsettled = _repo_sweep().unsettled
        if unsettled:
            self.fail(
                f"{len(unsettled)} round(s) never settle their variant pins, so "
                "the variants files do not determine what the round deploys:\n"
                + "\n".join(f"  - {label}: {why}" for label, why in unsettled.items())
                + "\n\nDrop the pin, or make the partner variant it selects stop "
                "deciding whether the pinning role joins the round."
            )

    def test_no_pin_in_force_stands_above_a_disabled_entry(self) -> None:
        dead = _repo_sweep().dead_pins
        if dead:
            self.fail(
                f"{len(dead)} pin(s) move a partner for a service entry the "
                "round switches off:\n"
                + "\n".join(f"  - {label}: {pin}" for label, pin in dead)
                + "\n\nDrop the pin, or move it above an entry the variant enables."
            )

    def test_some_round_moves_a_partner(self) -> None:
        self.assertTrue(
            _repo_sweep().moving,
            "no round has a pin that moves a partner off its clamped index, so "
            "the guard judges nothing; delete it if the mechanism is gone",
        )


class TestVariantPinGuardControls(unittest.TestCase):
    def _sweep_tree(self, files: Mapping[str, str]) -> Sweep:
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

    def test_an_oscillating_pin_pair_is_unsettled(self) -> None:
        sweep = self._sweep_tree(_oscillating_pair())
        self.assertIn(f"{HOST}#0", sweep.unsettled)
        self.assertFalse(sweep.dead_pins)

    def test_a_pin_above_a_disabled_entry_is_dead(self) -> None:
        sweep = self._sweep_tree(_pin_above_disabled_entry())
        self.assertFalse(sweep.unsettled)
        self.assertEqual(
            sweep.dead_pins,
            (
                (
                    f"{HOST}#0",
                    (
                        f"{HOST}#0 pins {RIGHT} above services.pin-right, "
                        "which the round runs with enabled: false"
                    ),
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
