"""The onion axis of the CI deploy matrix: what it may do, and to which rows.

Separate from :mod:`utils.github.variant.axes` because it answers a different
question. ``axes`` decides which combination a row takes this sweep; this
module decides which onion states exist for that row at all -- read off the
role's ``meta/services.yml``, off the covered variant, off the deploy mode,
and off the run's own ``tor`` input.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

ROLES_DIR = PROJECT_ROOT / "roles"

TOR_MODES = ("auto", "enforced", "exclusive", "disabled")

TOR_DEPLOY_MODES = ("swarm", "compose")


def _tor_flag(config: Mapping[str, Any]) -> Any:
    """The ``services.tor.enabled`` value of one config, or ``None`` if unset."""
    services = config.get("services") if isinstance(config, dict) else None
    tor = services.get("tor") if isinstance(services, dict) else None
    return tor.get("enabled") if isinstance(tor, dict) else None


def _base_tor_capable(app: str) -> bool:
    """Read the tor gate straight from the role's ``meta/services.yml``."""
    path = ROLES_DIR / app / ROLE_FILE_META_SERVICES
    if not path.exists():
        return True
    try:
        services = load_yaml_any(path) or {}
    except Exception:  # noqa: BLE001  malformed role meta must not break the matrix
        return True
    return _tor_flag({"services": services}) is not False


def tor_capable(
    app: str,
    variant: int | None = None,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> bool:
    """Whether a matrix row may be deployed behind the node onion.

    Args:
        app: application id.
        variant: the row's variant index; ``None`` for a role declaring none.
        variants_per_app: rendered variant configs per app; ``None`` falls back
            to the role's base ``meta/services.yml``.

    Returns:
        ``False`` when the covered variant pins ``services.tor.enabled`` to a
        literal false, ``True`` otherwise. A reactive Jinja flag counts as
        capable: it is the role saying "onion when the node is dark".
        Consulting the variant matters -- roles pin the gate ``true`` in
        variant 0 and ``false`` in the rest, so reading only the base config
        claims an onion for rounds that deliberately run without one.
    """
    declared = (variants_per_app or {}).get(app) or []
    if variant is None or not 0 <= variant < len(declared):
        return _base_tor_capable(app)
    return _tor_flag(declared[variant]) is not False


def tor_provider() -> str | None:
    """Application id of the role providing the ``tor`` service, ``None`` if
    the registry names none. Resolved rather than hardcoded so renaming the
    provider role cannot leave the matrix pointing at a dead id."""
    entry = build_service_registry_from_roles_dir(ROLES_DIR).get("tor") or {}
    role = entry.get("role")
    return role if isinstance(role, str) and role else None


def resolve_tor_mode(raw: str | None = None) -> str:
    """Tor axis mode from ``INFINITO_TOR``; unknown or empty means ``auto``.

    Args:
        raw: explicit value; ``None`` reads the environment.

    Returns:
        one of :data:`TOR_MODES`.
    """
    if raw is None:
        raw = os.environ.get("INFINITO_TOR")
    value = (raw or "").strip().lower()
    return value if value in TOR_MODES else "auto"


def wants_tor(position: int, sweep: int) -> bool:
    """Whether a capable row takes the onion this sweep. Halved on
    ``sweep // 2`` so it does not flip in lockstep with the mode rotation."""
    return (position + sweep // 2) % 2 == 0


def tor_states(mode: str, *, capable: bool, tor_mode: str) -> list[bool]:
    """The onion states one *mode* is worth running for a priority row.

    Args:
        mode: the deploy mode the row runs in.
        capable: whether the row's variant may take an onion at all.
        tor_mode: the run's tor axis.

    Returns:
        ``[True, False]`` on a tor-carrying mode under ``auto`` -- a priority
        row is not sampled, it covers both states in the same sweep. An
        explicit ``enforced``/``exclusive``/``disabled`` is an operator
        narrowing and still wins, and a mode that carries no onion axis at all
        (host) only ever yields the clearnet state.
    """
    if mode not in TOR_DEPLOY_MODES:
        return [False]
    if tor_mode == "disabled":
        return [False]
    if tor_mode in ("enforced", "exclusive"):
        if capable:
            return [True]
        return [] if tor_mode == "exclusive" else [False]
    return [True, False] if capable else [False]


def combinations(
    offered: Sequence[str], *, capable: bool, tor_mode: str
) -> list[tuple[str, bool]]:
    """Every ``(mode, tor)`` pair a priority row is deployed in.

    Priority rows are the ones a run must not sample: they cover the whole
    cross-product of the modes their role offers and the onion states each of
    those modes can take, in one sweep, instead of walking it over four.
    """
    return [
        (mode, enabled)
        for mode in offered
        for enabled in tor_states(mode, capable=capable, tor_mode=tor_mode)
    ]
