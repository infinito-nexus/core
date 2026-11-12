from __future__ import annotations

from collections.abc import Mapping

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.forms import SSO_ROOT, is_sso_source, iter_fields

OIDC_VARS = PROJECT_ROOT / "group_vars" / "all" / "11_oidc.yml"
OIDC_DEFAULTS = "defaults_oidc"
SSO_SOURCE_PARTS = 2


def claims() -> frozenset[str]:
    """Return the claim names defined in ``OIDC.ATTRIBUTES`` of the group vars."""
    oidc = load_yaml_any(str(OIDC_VARS), default_if_missing={}).get(OIDC_DEFAULTS)
    attributes = oidc.get("ATTRIBUTES") if isinstance(oidc, Mapping) else None
    if not isinstance(attributes, Mapping):
        return frozenset()
    return frozenset(value for value in attributes.values() if isinstance(value, str))


def errors(role: str, forms: Mapping) -> list[str]:
    """Return what keeps the ``sso.<claim>`` fields of a role from the schema.

    Args:
        role: role name, used in the findings.
        forms: the parsed ``meta/forms.yml``.

    Returns:
        One finding per ``sso`` source that is not ``sso.<claim>`` with a claim
        of ``OIDC.ATTRIBUTES``, per such field whose ``mode`` is not
        ``enforced`` and per such field with a ``when``; no finding repeats
        the source.
    """
    known = claims()
    found = []
    for form, field, spec in iter_fields(forms):
        source = spec.get("source")
        if not is_sso_source(source):
            continue
        where = f"{role}: {form}.{field}"
        parts = source.split(".")
        if len(parts) != SSO_SOURCE_PARTS or parts[1] not in known:
            found.append(
                f"{where}.source must be {SSO_ROOT}.<claim> with a claim of "
                f"OIDC.ATTRIBUTES {sorted(known)}"
            )
        if spec.get("mode") != "enforced":
            found.append(f"{where}.mode must be enforced, since the sign-in writes it")
        if "when" in spec:
            found.append(f"{where} takes no `when`; the selector's marker decides")
    return found


def selectors(forms: Mapping) -> dict[str, str]:
    """Return the selector of every ``sso.<claim>`` field, keyed by field.

    Args:
        forms: ``applications.<role>.forms`` or the parsed ``meta/forms.yml``.
    """
    return {
        field: spec["selector"]
        for _, field, spec in iter_fields(forms)
        if is_sso_source(spec.get("source")) and isinstance(spec.get("selector"), str)
    }


def only_sso(block: Mapping) -> bool:
    """Whether every field of one form names an ``sso.<claim>`` source.

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
