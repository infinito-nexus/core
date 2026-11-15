from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.applications.forms import (
    SourceError,
    _applies,
    _holds_template,
    is_sso_source,
    iter_fields,
    mapped,
    resolve,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _value(field: str, spec: Mapping, application: Mapping, users: Mapping) -> Any:
    value = resolve(spec["source"], application, users)
    if _holds_template(value):
        raise SourceError(
            f"{field} still holds template text, so the applications render "
            "failed on its source"
        )
    return mapped(spec, value)


def values(
    form: str,
    forms: Mapping,
    application: Mapping,
    users: Mapping,
    mode: str | None = None,
) -> dict[str, Any]:
    """Return what the sources of one form's applicable fields resolve to.

    Args:
        form: key of the form in ``meta/forms.yml``.
        forms: ``applications.<role>.forms``.
        application: the rendered ``applications.<role>``.
        users: the rendered global users.
        mode: keep only the fields of this mode; ``None`` keeps both.

    Returns:
        Each field whose ``when`` holds mapped to the value its ``source``
        resolves to, passed through its ``map``, in YAML order; an
        ``sso.<ATTRIBUTE>`` field and an ``optional`` field whose source is
        ``false`` are left out.

    Raises:
        SourceError: when a ``source`` or ``when`` names nothing, a source
            value still holds template text, or a ``map`` holds no entry for
            the source value.
    """
    return {
        field: _value(field, spec, application, users)
        for name, field, spec in iter_fields(forms)
        if name == form
        and not is_sso_source(spec.get("source"))
        and (mode is None or spec.get("mode") == mode)
        and _applies(spec, application, users)
    }
