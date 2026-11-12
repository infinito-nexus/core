from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.applications.forms import (
    _applies,
    is_sso_source,
    iter_fields,
    mapped,
    resolve,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


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
        ``sso.<claim>`` field is left out.

    Raises:
        SourceError: when a ``source`` or ``when`` names nothing, or a ``map``
            holds no entry for the source value.
    """
    return {
        field: mapped(spec, resolve(spec["source"], application, users))
        for name, field, spec in iter_fields(forms)
        if name == form
        and not is_sso_source(spec.get("source"))
        and (mode is None or spec.get("mode") == mode)
        and _applies(spec, application, users)
    }
