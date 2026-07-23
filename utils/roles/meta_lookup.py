"""Helpers for reading per-role metadata that lives on the role's primary
service entity in `meta/services.yml`.

Both fields used to live nested inside `meta/main.yml.galaxy_info`:

  * ``run_after``  — project-specific role-load-order list.
  * ``lifecycle``  — maturity marker filtered by
    ``cli meta roles lifecycle``.

They live at
``meta/services.yml.<primary_entity>.{run_after,lifecycle}`` where
``<primary_entity>`` is the value returned by
:func:`utils.roles.entity.name.get_entity_name` for the role's directory
name.

Both helpers degrade gracefully:
  * ``[]`` / ``None`` when ``meta/services.yml`` is absent OR the field is
    absent on the primary entity.
  * Raise a clear error only when ``meta/services.yml`` exists and parses
    into a wrong-shape document (non-dict root, non-dict primary entry).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_TESTS

from . import PROJECT_ROOT

PathLike = str | Path


class MetaServicesShapeError(ValueError):
    """Raised when ``meta/services.yml`` is malformed."""


def _read_meta_services(role_dir: Path) -> dict | None:
    services_path = role_dir / ROLE_FILE_META_SERVICES
    if not services_path.is_file():
        return None
    try:
        loaded = load_yaml_any(str(services_path))
    except yaml.YAMLError as exc:
        raise MetaServicesShapeError(
            f"{services_path} is not valid YAML: {exc}"
        ) from exc
    if loaded in (None, {}):
        return None
    if not isinstance(loaded, dict):
        raise MetaServicesShapeError(
            f"{services_path} must be a YAML mapping at the file root."
        )
    return loaded


def _read_meta_tests(role_dir: Path) -> dict | None:
    tests_path = role_dir / ROLE_FILE_META_TESTS
    if not tests_path.is_file():
        return None
    try:
        loaded = load_yaml_any(str(tests_path))
    except yaml.YAMLError as exc:
        raise MetaServicesShapeError(f"{tests_path} is not valid YAML: {exc}") from exc
    if loaded in (None, {}):
        return None
    if not isinstance(loaded, dict):
        raise MetaServicesShapeError(
            f"{tests_path} must be a YAML mapping at the file root."
        )
    return loaded


def _primary_entry(role_name: str, services: dict | None) -> dict | None:
    if not services:
        return None
    primary_entity = get_entity_name(role_name) or role_name
    entry = services.get(primary_entity)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise MetaServicesShapeError(
            f"meta/services.yml entry for primary entity "
            f"'{primary_entity}' (role '{role_name}') must be a mapping; "
            f"got {type(entry).__name__}."
        )
    return entry


def get_role_run_after(role: PathLike, *, role_name: str | None = None) -> list[str]:
    """Return the role's ``run_after`` list (or ``[]`` when absent).

    ``role`` may be a role name (relative to ``roles/``) or an absolute
    path to a role directory. Pass ``role_name`` explicitly when
    ``role`` is an arbitrary path whose basename is not the canonical
    role name.
    """
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return []
    raw = primary.get("run_after")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MetaServicesShapeError(
            f"Invalid run_after type in meta/services.yml for role '{name}': "
            f"expected list, got {type(raw).__name__}."
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise MetaServicesShapeError(
                f"Invalid run_after entry in meta/services.yml for role "
                f"'{name}': {item!r} (expected non-empty string)."
            )
        out.append(item.strip())
    return out


def get_role_lifecycle(role: PathLike, *, role_name: str | None = None) -> str | None:
    """Return the role's ``lifecycle`` string (or ``None`` when absent)."""
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return None
    raw = primary.get("lifecycle")
    if raw is None:
        return None
    if isinstance(raw, dict):
        stage = raw.get("stage")
        return str(stage).strip().lower() if isinstance(stage, str) else None
    return str(raw).strip().lower() if isinstance(raw, str) else None


MODES: tuple[str, ...] = ("compose", "swarm", "host")
"""Every deploy mode a role's primary entity may toggle. ``compose``/``swarm``
target stack roles (own container stack); ``host`` targets invokable roles that
configure the host instead of shipping a stack."""

DEPLOY_MODES: tuple[str, ...] = ("compose", "swarm")
"""The stack deploy modes the CI test-deploy matrix (get_role_skip) covers."""


def get_role_mode_enabled(
    role: PathLike, *, mode: str, role_name: str | None = None
) -> bool:
    """Return whether the role opts into deploy ``mode`` (``compose`` |
    ``swarm`` | ``host``).

    The SPOT is ``meta/services.yml.<primary_entity>.modes.<mode>.enabled``.
    A missing ``modes`` block, a missing ``<mode>`` entry, or a missing
    ``enabled`` key all mean the role participates in that mode (default
    ``True``)."""
    if mode not in MODES:
        raise ValueError(f"Unknown deploy mode {mode!r}; expected one of {MODES}.")
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return True
    modes = primary.get("modes")
    if modes is None:
        return True
    if not isinstance(modes, dict):
        raise MetaServicesShapeError(
            f"Invalid modes type in meta/services.yml for role '{name}': "
            f"expected mapping, got {type(modes).__name__}."
        )
    entry = modes.get(mode)
    if entry is None:
        return True
    if not isinstance(entry, dict):
        raise MetaServicesShapeError(
            f"Invalid modes.{mode} type in meta/services.yml for role '{name}': "
            f"expected mapping, got {type(entry).__name__}."
        )
    enabled = entry.get("enabled")
    if enabled is None:
        return True
    if not isinstance(enabled, bool):
        raise MetaServicesShapeError(
            f"Invalid modes.{mode}.enabled in meta/services.yml for role "
            f"'{name}': expected bool, got {type(enabled).__name__}."
        )
    return enabled


def get_role_skip(role: PathLike, *, role_name: str | None = None) -> list[str]:
    """Return the deploy modes the role is excluded from in test-deploy
    discovery (e.g. ``[compose, swarm]``), or ``[]`` when it participates in
    all of them.

    Derived from ``meta/services.yml.<primary_entity>.modes.<mode>.enabled``:
    a mode is skipped iff its ``enabled`` flag is ``false``."""
    role_dir, name = _resolve_role(role, role_name)
    return [
        mode
        for mode in DEPLOY_MODES
        if not get_role_mode_enabled(role_dir, mode=mode, role_name=name)
    ]


def get_role_test_skips(role: PathLike, *, role_name: str | None = None) -> list[str]:
    """Return the deploy modes deactivated for test-deploy discovery via
    ``meta/tests.yml`` ``skip``, or ``[]`` when absent.

    ``modes`` in ``meta/services.yml`` states where a role RUNS;
    ``skip`` in ``meta/tests.yml`` deactivates TESTING a mode without
    touching that capability."""
    role_dir, name = _resolve_role(role, role_name)
    tests = _read_meta_tests(role_dir)
    if tests is None:
        return []
    raw = tests.get("skip")
    if raw is None:
        return []
    if not isinstance(raw, list) or any(m not in MODES for m in raw):
        raise MetaServicesShapeError(
            f"Invalid skip in meta/tests.yml for role '{name}': {raw!r} "
            f"(expected a list drawn from {MODES})."
        )
    return [str(m) for m in raw]


def get_role_variant_bundle_size(
    role: PathLike, *, role_name: str | None = None
) -> int | None:
    """Return the role's ``variant_bundle_size`` from ``meta/tests.yml`` (the
    per-role cap on variants per compose CI job), or ``None`` when absent."""
    role_dir, name = _resolve_role(role, role_name)
    tests = _read_meta_tests(role_dir)
    if tests is None:
        return None
    raw = tests.get("variant_bundle_size")
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise MetaServicesShapeError(
            f"Invalid variant_bundle_size in meta/tests.yml for role "
            f"'{name}': {raw!r} (expected integer >= 1)."
        )
    return raw


def get_role_placement(role: PathLike, *, role_name: str | None = None) -> str | None:
    """Return the role's ``placement`` string (or ``None`` when absent)."""
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return None
    raw = primary.get("placement")
    if raw is None:
        return None
    return str(raw).strip()


def iter_roles_with_placement(
    placement: str, *, roles_dir: PathLike | None = None
) -> list[str]:
    """Sorted role names whose primary entity declares ``placement: <placement>``."""
    if not placement:
        return []
    base = Path(roles_dir) if roles_dir is not None else PROJECT_ROOT / "roles"
    if not base.is_dir():
        return []
    matches: list[str] = []
    for role_dir in sorted(base.iterdir()):
        if not role_dir.is_dir():
            continue
        try:
            value = get_role_placement(role_dir, role_name=role_dir.name)
        except MetaServicesShapeError:
            continue
        if value == placement:
            matches.append(role_dir.name)
    return matches


def _resolve_role(role: PathLike, role_name: str | None) -> tuple[Path, str]:
    role_path = Path(role)
    if role_path.is_absolute() or role_path.parts[:1] == (".",):
        role_dir = role_path.resolve()
    else:
        repo_root = PROJECT_ROOT
        role_dir = repo_root / "roles" / str(role)
    name = role_name or role_dir.name
    return role_dir, name
