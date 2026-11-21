"""Variant pins: ``# variant-pin: <role>#<index|reciprocal|without-<key>>``.

A matrix round hands every role the round index, clamping to variant 0 when
the role has fewer entries (:func:`services_overrides_for_round`). A pairing
therefore holds only while two independently maintained variant lists happen
to agree on an index, and it breaks silently the moment the partner has fewer
variants than the round.

A pin states the dependency instead of inheriting it. Written as a comment on
the line above the service entry that creates the dependency, it keeps the
runtime services map clean: the marker never reaches ``host_vars``, unlike a
YAML key under the service would::

    # variant-pin: web-app-nextcloud#3
    nextcloud:
      enabled: true
      shared: true

``#reciprocal`` resolves to the partner's variant that switches this role back
on, so neither side has to track the other's index::

    # variant-pin: web-app-nextcloud#reciprocal

Two roles in one round pinning the same partner to different variants is a
maintenance error with no sound resolution, so it raises
:class:`VariantPinConflictError` before an inventory is written.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

PIN = re.compile(
    r"#\s*variant-pin:\s*([a-z0-9][a-z0-9-]*)\s*#\s*"
    r"(\d+|reciprocal|without-[a-z0-9_-]+)\b",
    re.IGNORECASE,
)
_GROUP_MEMBERSHIP = re.compile(r"'([a-z0-9][a-z0-9-]*)'\s+in\s+group_names")

RECIPROCAL = "reciprocal"
WITHOUT = "without-"


class VariantPinError(ValueError):
    """A pin cannot be resolved."""


class VariantPinConflictError(VariantPinError):
    """Two roles pin the same partner to different variants in one round."""


def _service_key_lines(text: str) -> dict[int, dict[str, int]]:
    """Map variant index -> {service key: 0-based line of that key}."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise VariantPinError(f"variants file is not valid YAML: {exc}") from exc
    if not isinstance(root, yaml.SequenceNode):
        return {}
    per_variant: dict[int, dict[str, int]] = {}
    for index, entry in enumerate(root.value):
        if not isinstance(entry, yaml.MappingNode):
            continue
        for key_node, value_node in entry.value:
            if getattr(key_node, "value", None) != "services":
                continue
            if not isinstance(value_node, yaml.MappingNode):
                continue
            per_variant[index] = {
                str(service_key.value): service_key.start_mark.line
                for service_key, _ in value_node.value
            }
    return per_variant


@functools.cache
def pins_of(role: str, *, roles_dir: str) -> dict[int, dict[str, str]]:
    """Map variant index -> {partner role: target} for one role's variants."""
    path = Path(roles_dir) / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return {}
    text = read_text(str(path))
    lines = text.splitlines()
    found: dict[int, dict[str, str]] = {}
    for index, keys in _service_key_lines(text).items():
        for _service_key, line_no in sorted(keys.items(), key=lambda kv: kv[1]):
            if line_no == 0:
                continue
            match = PIN.search(lines[line_no - 1])
            if not match:
                continue
            partner, target = match.group(1), match.group(2).lower()
            found.setdefault(index, {})[partner] = target
    return found


def _reciprocal_key(partner: str, role: str, *, roles_dir: str) -> str | None:
    """The key in *partner* whose enabled gate names *role*."""
    services = load_yaml_any(Path(roles_dir) / partner / ROLE_FILE_META_SERVICES)
    if not isinstance(services, dict):
        return None
    for key, entry in services.items():
        if not isinstance(entry, dict):
            continue
        match = _GROUP_MEMBERSHIP.search(str(entry.get("enabled", "")))
        if match and match.group(1) == role:
            return str(key)
    return None


def _variants_setting(
    partner: str, key: str, enabled: bool, *, variants_per_app: Mapping[str, list]
) -> list[int]:
    return [
        index
        for index, variant in enumerate(variants_per_app.get(partner) or [])
        if isinstance(variant, Mapping)
        and isinstance((variant.get("services") or {}).get(key), Mapping)
        and (variant["services"][key]).get("enabled") is enabled
    ]


def _reciprocal_index(
    partner: str,
    role: str,
    *,
    roles_dir: str,
    variants_per_app: Mapping[str, list],
) -> int:
    key = _reciprocal_key(partner, role, roles_dir=roles_dir)
    if key is None:
        raise VariantPinError(
            f"{role} pins {partner}#reciprocal, but {partner}'s "
            f"{ROLE_FILE_META_SERVICES} declares no service gating on {role}"
        )
    hits = _variants_setting(partner, key, True, variants_per_app=variants_per_app)
    if len(hits) != 1:
        raise VariantPinError(
            f"{role} pins {partner}#reciprocal, but {partner} pins "
            f"services.{key} to literal true in {len(hits)} variants "
            f"({hits or 'none'}); reciprocal needs exactly one"
        )
    return hits[0]


def _without_index(
    partner: str, key: str, role: str, *, variants_per_app: Mapping[str, list]
) -> int:
    hits = _variants_setting(partner, key, False, variants_per_app=variants_per_app)
    if len(hits) != 1:
        raise VariantPinError(
            f"{role} pins {partner}#{WITHOUT}{key}, but {partner} pins "
            f"services.{key} to literal false in {len(hits)} variants "
            f"({hits or 'none'}); {WITHOUT}<key> needs exactly one"
        )
    return hits[0]


def intended_index(
    partner: str,
    role: str,
    target: str,
    *,
    roles_dir: str,
    variants_per_app: Mapping[str, list],
) -> int:
    """
    Args:
        partner: the pinned role.
        role: the carrier role.
        target: the pin target, an index, ``reciprocal`` or ``without-<key>``.
        roles_dir: the roles tree the partner's services are read from.
        variants_per_app: parsed variants per role.

    Returns:
        The single variant ``without-<key>`` resolves to; for every other
        target, the variant that switches *role* back on.

    Raises:
        VariantPinError: the target resolves to no variant or to several.
    """
    if target.startswith(WITHOUT):
        return _without_index(
            partner,
            target.removeprefix(WITHOUT),
            role,
            variants_per_app=variants_per_app,
        )
    return _reciprocal_index(
        partner, role, roles_dir=roles_dir, variants_per_app=variants_per_app
    )


def resolve_pins(
    active_index: Mapping[str, int],
    *,
    roles_dir: str,
    variants_per_app: Mapping[str, list],
) -> dict[str, int]:
    """Pins contributed by the variant each role runs in this round.

    Args:
        active_index: role -> the variant index the round selected for it.
        roles_dir: the roles tree the variants are read from.
        variants_per_app: parsed variants per role.

    Returns:
        role -> the variant index a pin forces it to, for pinned roles only.

    Raises:
        VariantPinConflictError: two roles pin one partner to different variants.
        VariantPinError: a pin names an out-of-range or unresolvable variant.
    """
    resolved: dict[str, int] = {}
    source: dict[str, str] = {}
    for role, index in sorted(active_index.items()):
        for partner, target in sorted(
            pins_of(role, roles_dir=roles_dir).get(index, {}).items()
        ):
            count = len(variants_per_app.get(partner) or [])
            if target.isdigit():
                wanted = int(target)
                if not 0 <= wanted < count:
                    raise VariantPinError(
                        f"{role}#{index} pins {partner}#{wanted}, but {partner} "
                        f"declares {count} variant(s)"
                    )
            else:
                wanted = intended_index(
                    partner,
                    role,
                    target,
                    roles_dir=roles_dir,
                    variants_per_app=variants_per_app,
                )
            if partner in resolved and resolved[partner] != wanted:
                raise VariantPinConflictError(
                    f"{source[partner]} pins {partner}#{resolved[partner]} while "
                    f"{role}#{index} pins {partner}#{wanted}; one round cannot "
                    f"deploy {partner} in two variants"
                )
            resolved[partner] = wanted
            source[partner] = f"{role}#{index}"
    return resolved
