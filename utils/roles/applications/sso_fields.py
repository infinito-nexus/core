from __future__ import annotations

from collections.abc import Mapping

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.forms import (
    SSO_ROOT,
    SourceError,
    is_sso_source,
    iter_fields,
)

OIDC_VARS = PROJECT_ROOT / "group_vars" / "all" / "11_oidc.yml"
OIDC_DEFAULTS = "defaults_oidc"
OIDC_ATTRIBUTES = "ATTRIBUTES"
SSO_SOURCE_PARTS = 2


def attributes() -> dict[str, str]:
    """Return ``OIDC.ATTRIBUTES`` of the group vars: each attribute key with its claim."""
    oidc = load_yaml_any(str(OIDC_VARS), default_if_missing={}).get(OIDC_DEFAULTS)
    named = oidc.get(OIDC_ATTRIBUTES) if isinstance(oidc, Mapping) else None
    if not isinstance(named, Mapping):
        return {}
    return {str(key): value for key, value in named.items() if isinstance(value, str)}


def _rule(named: Mapping[str, str]) -> str:
    return (
        f"must be {SSO_ROOT}.<ATTRIBUTE> with an attribute key of "
        f"OIDC.ATTRIBUTES {sorted(named)}"
    )


def claim(source: str, named: Mapping[str, str]) -> str:
    """Return the claim an ``sso.<ATTRIBUTE>`` source reads.

    Args:
        source: the field's ``source``.
        named: ``OIDC.ATTRIBUTES``, each attribute key with its claim.

    Raises:
        SourceError: when the source is no ``sso.<ATTRIBUTE>`` with a key of
            ``named``; the message lists the keys and never repeats the source.
    """
    parts = source.split(".") if isinstance(source, str) else []
    if len(parts) != SSO_SOURCE_PARTS or parts[0] != SSO_ROOT or parts[1] not in named:
        raise SourceError(f"the source {_rule(named)}")
    return named[parts[1]]


def errors(role: str, forms: Mapping) -> list[str]:
    """Return what keeps the ``sso.<ATTRIBUTE>`` fields of a role from the schema.

    Args:
        role: role name, used in the findings.
        forms: the parsed ``meta/forms.yml``.

    Returns:
        One finding per ``sso`` source that ``claim`` refuses, per such field
        whose ``mode`` is not ``enforced``, per such field with a ``when`` and
        per such field whose form declares a ``record``; no finding repeats
        the source.
    """
    named = attributes()
    found = []
    for form, field, spec in iter_fields(forms):
        source = spec.get("source")
        if not is_sso_source(source):
            continue
        where = f"{role}: {form}.{field}"
        try:
            claim(source, named)
        except SourceError:
            found.append(f"{where}.source {_rule(named)}")
        if spec.get("mode") != "enforced":
            found.append(f"{where}.mode must be enforced, since the sign-in writes it")
        if "when" in spec:
            found.append(f"{where} takes no `when`; the selector's marker decides")
        if "record" in forms.get(form, {}):
            found.append(f"{where} takes no `record`; the selector's marker decides")
    return found


def selectors(forms: Mapping) -> dict[str, str]:
    """Return the selector of every ``sso.<ATTRIBUTE>`` field, keyed by field.

    Args:
        forms: ``applications.<role>.forms`` or the parsed ``meta/forms.yml``.
    """
    return {
        field: spec["selector"]
        for _, field, spec in iter_fields(forms)
        if is_sso_source(spec.get("source")) and isinstance(spec.get("selector"), str)
    }


def only_sso(block: Mapping) -> bool:
    """Whether every field of one form names an ``sso.<ATTRIBUTE>`` source.

    Args:
        block: one form of ``meta/forms.yml``.
    """
    fields = block.get("fields") if isinstance(block, Mapping) else None
    return (
        isinstance(fields, Mapping)
        and bool(fields)
        and all(
            isinstance(spec, Mapping) and is_sso_source(spec.get("source"))
            for spec in fields.values()
        )
    )
