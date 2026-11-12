"""Managed fields a role declares in ``meta/forms.yml``.

``meta/forms.yml`` maps each admin form of the application to its page and
the fields the role converges into it::

    general:
      path: /wp-admin/options-general.php
      fields:
        admin_email:
          source: users.platform_administrator.email
          mode: seeded
          selector: "#new_admin_email"

``source`` is an inventory path relative to ``applications.<role>``; a path
under ``users`` points to the global users and must be exactly
``users.<key>.<attr>``, with an attr other than ``tokens``; ``sso.<claim>``
names the claim the SSO sign-in writes into a profile field, which no
converge, drift line or banner covers. The generic meta
loader places the file at ``applications.<role>.forms``, so an inventory
overrides a single field under
``applications.<role>.forms.<form>.fields.<field>``; the forms stay out of the
templar, so an override is never rendered.

``locks`` hands every ``enforced`` field whose ``when`` holds to the shared
lock renderer of ``sys-front-inj-javascript``, an ``sso.<claim>`` field as a
profile lock without unlock; a ``seeded`` field never reaches the page.

The drift report fails closed: it shows old and new values only for a field
that declares a type from ``SHOWN_TYPES``, whose source lies outside ``users``
and the credentials, has no segment matching ``SECRET_SEGMENT`` or naming a
declared credential, resolves in the unrendered application to a plain scalar
with no template, and whose values are plain scalars that hold no URL userinfo and
neither equal nor contain a secret of ``drift.secret_values``. Every other change
reads ``changed`` without either value. No finding, error or line repeats a
source that did not resolve. Every forms string must hold no template, since
the forms are never rendered.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from ansible.module_utils.parsing.convert_bool import boolean

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SECRETS

if TYPE_CHECKING:
    from pathlib import Path

MODES = ("enforced", "seeded")
TYPES = (
    "checkbox",
    "color",
    "email",
    "number",
    "password",
    "select",
    "text",
    "textarea",
    "url",
)
FORM_KEYS = frozenset({"path", "fields", "sinks"})
REQUIRED_FIELD_KEYS = ("source", "mode", "selector")
OPTIONAL_FIELD_KEYS = frozenset(
    {"when", "label", "type", "enum", "validation", "description", "map"}
)
NEGATION = "!"
MAP_SCALARS = (str, int, float, bool)
USERS_ROOT = "users"
SSO_ROOT = "sso"
USER_SOURCE_PARTS = 3
USER_REFUSED_ATTRIBUTES = frozenset({"tokens"})
CREDENTIALS_ROOT = ("secrets", "credentials")
CREDENTIAL_LEAF_MARKERS = frozenset(
    {"default", "algorithm", "validation", "description"}
)
SHOWN_TYPES = frozenset(
    {"checkbox", "color", "email", "number", "select", "text", "textarea", "url"}
)
SECRET_SEGMENT = re.compile(
    r"pass|secret|token|key|pin|credential|bind|pw|salt|bearer|webhook",
    re.IGNORECASE,
)
TEMPLATE_MARKERS = ("{{", "{%")

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")
_SINK = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SourceError(KeyError):
    """A ``source`` or ``when`` path names nothing in the inventory; the
    message never repeats the path."""


def iter_fields(forms: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping]]:
    """Yield every declared field of well-formed forms.

    Args:
        forms: ``applications.<role>.forms``.

    Returns:
        ``(form, field, spec)`` in YAML order; malformed entries are skipped,
        ``schema_errors`` reports them.
    """
    for form, block in forms.items():
        fields = block.get("fields") if isinstance(block, Mapping) else None
        if not isinstance(fields, Mapping):
            continue
        for field, spec in fields.items():
            if isinstance(spec, Mapping):
                yield str(form), str(field), spec


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def when_path(when: Any) -> Any:
    """Return the inventory path of a ``when``, without its negation.

    Args:
        when: the field's ``when``.
    """
    if isinstance(when, str) and when.startswith(NEGATION):
        return when[len(NEGATION) :]
    return when


def _holds_template(value: Any) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in TEMPLATE_MARKERS)
    if isinstance(value, Mapping):
        return any(_holds_template(child) for child in value.values())
    if isinstance(value, list):
        return any(_holds_template(child) for child in value)
    return False


def _template_errors(where: str, block: Mapping, keys: Iterator[str]) -> list[str]:
    return [
        f"{where}.{key} must hold no template; {ROLE_FILE_META_FORMS} is never rendered"
        for key in keys
        if _holds_template(block.get(key))
    ]


def _field_errors(where: str, spec: Any) -> list[str]:
    if not isinstance(spec, Mapping):
        return [f"{where} must be a mapping"]
    known = {*REQUIRED_FIELD_KEYS, *OPTIONAL_FIELD_KEYS}
    errors = [
        f"{where}.{key} is not a known key; use {sorted(known)}"
        for key in sorted(set(spec) - known)
    ]
    errors.extend(_template_errors(where, spec, iter(sorted(map(str, spec)))))
    errors.extend(
        f"{where} lacks `{key}`" for key in REQUIRED_FIELD_KEYS if key not in spec
    )
    errors.extend(
        f"{where}.{key} must be a dotted inventory path"
        for key, path in (
            ("source", spec.get("source")),
            ("when", when_path(spec.get("when"))),
        )
        if key in spec and not (isinstance(path, str) and _PATH.fullmatch(path))
    )
    if "mode" in spec and spec["mode"] not in MODES:
        errors.append(f"{where}.mode {spec['mode']!r} is not one of {list(MODES)}")
    errors.extend(
        f"{where}.{key} must be a non-empty string"
        for key in ("selector", "label", "description")
        if key in spec and not _non_empty_string(spec[key])
    )
    if "type" in spec and spec["type"] not in TYPES:
        errors.append(f"{where}.type {spec['type']!r} is not one of {list(TYPES)}")
    if "enum" in spec and not (isinstance(spec["enum"], list) and spec["enum"]):
        errors.append(f"{where}.enum must be a non-empty list")
    if "validation" in spec:
        errors.extend(_validation_errors(where, spec["validation"]))
    if "map" in spec:
        errors.extend(_map_errors(where, spec["map"]))
    return errors


def _map_errors(where: str, table: Any) -> list[str]:
    if (
        isinstance(table, Mapping)
        and table
        and all(
            isinstance(key, MAP_SCALARS) and isinstance(value, MAP_SCALARS)
            for key, value in table.items()
        )
    ):
        return []
    return [f"{where}.map must map each source value to a scalar the app stores"]


def _validation_errors(where: str, validation: Any) -> list[str]:
    if not _non_empty_string(validation):
        return [f"{where}.validation must be a regular expression"]
    try:
        re.compile(validation)
    except re.error as error:
        return [f"{where}.validation is no regular expression: {error}"]
    return []


def _sinks_errors(where: str, sinks: Any) -> list[str]:
    if (
        isinstance(sinks, list)
        and sinks
        and all(isinstance(sink, str) and _SINK.fullmatch(sink) for sink in sinks)
        and len(set(sinks)) == len(sinks)
    ):
        return []
    return [
        (
            f"{where}.sinks must list distinct UPPER_SNAKE_CASE role variables"
            " that carry the form's values"
        )
    ]


def _form_errors(where: str, block: Any) -> list[str]:
    if not isinstance(block, Mapping):
        return [f"{where} must be a mapping of {sorted(FORM_KEYS)}"]
    errors = [
        f"{where}.{key} is not a known key; use {sorted(FORM_KEYS)}"
        for key in sorted(set(block) - FORM_KEYS)
    ]
    errors.extend(_template_errors(where, block, iter(("path",))))
    path = block.get("path")
    if not (_non_empty_string(path) and path.startswith("/")):
        errors.append(f"{where}.path must be the admin page path, starting with /")
    if "sinks" in block:
        errors.extend(_sinks_errors(where, block["sinks"]))
    fields = block.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        errors.append(f"{where}.fields must map each field to its spec")
        return errors
    for field, spec in fields.items():
        if not (isinstance(field, str) and _KEY.fullmatch(field)):
            errors.append(f"{where}.fields: {field!r} is no lower snake_case key")
        errors.extend(_field_errors(f"{where}.fields.{field}", spec))
    return errors


def schema_errors(role: str, forms: Any) -> list[str]:
    """Return what keeps a role's ``meta/forms.yml`` from the schema.

    Args:
        role: role name, used in the findings.
        forms: the parsed ``meta/forms.yml``.
    """
    if not isinstance(forms, Mapping) or not forms:
        return [
            f"{role}: {ROLE_FILE_META_FORMS} must map each form to its path and fields"
        ]
    errors = []
    for form, block in forms.items():
        if not (isinstance(form, str) and _KEY.fullmatch(form)):
            errors.append(f"{role}: form {form!r} is no lower snake_case key")
        errors.extend(_form_errors(f"{role}: {form}", block))
    return errors


def _walk(node: Any, parts: list[str], source: str) -> Any:
    for part in parts:
        if not isinstance(node, Mapping) or part not in node:
            raise SourceError("the source names nothing in the inventory")
        node = node[part]
    return node


def _is_user_path(parts: list[str]) -> bool:
    return parts[0] == USERS_ROOT


def is_sso_source(source: Any) -> bool:
    """Whether a field's ``source`` names a claim of the SSO sign-in.

    Args:
        source: the field's ``source``.
    """
    return isinstance(source, str) and source.split(".", 1)[0] == SSO_ROOT


def _is_allowed_user_path(parts: list[str]) -> bool:
    return (
        len(parts) == USER_SOURCE_PARTS
        and parts[0] == USERS_ROOT
        and parts[2] not in USER_REFUSED_ATTRIBUTES
    )


def _is_credential_source(parts: list[str]) -> bool:
    return tuple(parts[: len(CREDENTIALS_ROOT)]) == CREDENTIALS_ROOT


def resolve(source: str, application: Mapping, users: Mapping) -> Any:
    """Return the inventory value a field's ``source`` names.

    Args:
        source: dotted path relative to ``applications.<role>``, or
            ``users.<key>.<attr>`` with an attr other than ``tokens``.
        application: ``applications.<role>``.
        users: the global users.

    Raises:
        SourceError: when the source is no dotted path, names nothing, names
            a user path of another shape or a refused user attribute, or names
            an SSO claim; the message never repeats the source.
    """
    if not (isinstance(source, str) and _PATH.fullmatch(source)):
        raise SourceError("the source is no dotted inventory path")
    if is_sso_source(source):
        raise SourceError("an sso source has no deploy-time value")
    parts = source.split(".")
    if not _is_user_path(parts):
        return _walk(application, parts, source)
    if not _is_allowed_user_path(parts):
        raise SourceError("the source is no allowed users.<key>.<attr> path")
    return _walk(users, parts[1:], source)


def role_credentials(role_dir: Path) -> Mapping:
    """Return the ``credentials`` tree of a role's ``meta/secrets.yml``.

    Args:
        role_dir: the role's directory.
    """
    secrets = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SECRETS), default_if_missing={}
    )
    credentials = secrets.get("credentials") if isinstance(secrets, Mapping) else None
    return credentials if isinstance(credentials, Mapping) else {}


def _credential_leaf(credentials: Mapping, parts: list[str]) -> bool:
    try:
        node = _walk(credentials, parts, ".".join(parts))
    except SourceError:
        return False
    return isinstance(node, Mapping) and bool(CREDENTIAL_LEAF_MARKERS & set(node))


def declares(
    source: str, application: Mapping, users: Mapping, credentials: Mapping
) -> bool:
    """Whether ``source`` resolves before the inventory generates credentials.

    Args:
        source: dotted path relative to ``applications.<role>``, or
            ``users.<key>.<attr>``.
        application: the role's ``applications.<role>`` defaults.
        users: the global user defaults.
        credentials: the ``credentials`` tree of the role's ``meta/secrets.yml``.

    Returns:
        True when the path exists in the defaults, or names a credential the
        role's ``meta/secrets.yml`` declares.
    """
    parts = source.split(".")
    if _is_credential_source(parts) and _credential_leaf(
        credentials, parts[len(CREDENTIALS_ROOT) :]
    ):
        return True
    try:
        resolve(source, application, users)
    except SourceError:
        return False
    return True


def source_errors(
    role: str,
    forms: Mapping,
    application: Mapping,
    users: Mapping,
    credentials: Mapping,
) -> list[str]:
    """Return every ``source`` and ``when`` of a role that is refused or resolves to nothing.

    Args:
        role: role name, used in the findings.
        forms: the parsed ``meta/forms.yml``.
        application: the role's ``applications.<role>`` defaults.
        users: the global user defaults.
        credentials: the ``credentials`` tree of the role's ``meta/secrets.yml``.

    Returns:
        One finding per refused or unresolved path, naming the
        ``<form>.<field>.<key>`` coordinate and never the path itself; an
        ``sso.<claim>`` source is left to ``sso_fields.errors``.
    """
    errors = []
    for form, field, spec in iter_fields(forms):
        for key, path in (
            ("source", spec.get("source")),
            ("when", when_path(spec.get("when"))),
        ):
            if not (isinstance(path, str) and _PATH.fullmatch(path)):
                continue
            if key == "source" and is_sso_source(path):
                continue
            where = f"{role}: {form}.{field}.{key}"
            parts = path.split(".")
            if _is_user_path(parts) and not _is_allowed_user_path(parts):
                errors.append(
                    f"{where} must be users.<key>.<attr> with an attr other than "
                    f"{sorted(USER_REFUSED_ATTRIBUTES)}"
                )
            elif not declares(path, application, users, credentials):
                errors.append(f"{where} names nothing in the inventory")
    return errors


def _credential_names(node: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(node, Mapping):
        return names
    for key, value in node.items():
        if isinstance(value, Mapping) and CREDENTIAL_LEAF_MARKERS & set(value):
            names.add(str(key))
        else:
            names |= _credential_names(value)
    return names


def is_secret(source: str, credentials: Mapping) -> bool:
    """Whether the drift report must not show the values of a source.

    Args:
        source: the field's ``source``.
        credentials: the ``credentials`` tree of the role's ``meta/secrets.yml``.

    Returns:
        True for a value that is no inventory path, for any path under
        ``users`` or ``secrets.credentials``, for a path with a segment that
        matches ``SECRET_SEGMENT``, and for a path with a segment named like a
        credential the role declares, all case-insensitive.
    """
    if not (isinstance(source, str) and _PATH.fullmatch(source)):
        return True
    parts = source.split(".")
    names = {name.lower() for name in _credential_names(credentials)}
    return (
        _is_user_path(parts)
        or _is_credential_source(parts)
        or any(SECRET_SEGMENT.search(part) for part in parts)
        or bool({part.lower() for part in parts} & names)
    )


def _plain_field(spec: Mapping, credentials: Mapping) -> bool:
    field_type = spec.get("type")
    return (
        isinstance(field_type, str)
        and field_type in SHOWN_TYPES
        and not is_secret(spec.get("source"), credentials)
    )


def inventory_path(role: str, source: str) -> str:
    """Return the inventory path that holds the value of a field.

    Args:
        role: role name; every source outside ``users`` lies under
            ``applications.<role>``.
        source: the field's ``source``.
    """
    if _is_user_path(source.split(".")):
        return source
    return f"applications.{role}.{source}"


def _applies(spec: Mapping, application: Mapping, users: Mapping) -> bool:
    if "when" not in spec:
        return True
    holds = boolean(resolve(when_path(spec["when"]), application, users), strict=False)
    return holds != spec["when"].startswith(NEGATION)


def mapped(spec: Mapping, value: Any) -> Any:
    """Return the value the application stores for a field's source value.

    Args:
        spec: the field's spec; without ``map`` the value is stored as is.
        value: what the field's ``source`` resolves to.

    Raises:
        SourceError: when ``map`` holds no entry for the value; the message
            never repeats it.
    """
    table = spec.get("map")
    if table is None:
        return value
    if isinstance(value, MAP_SCALARS) and value in table:
        return table[value]
    if all(isinstance(key, bool) for key in table):
        try:
            return table[boolean(value, strict=True)]
        except (TypeError, KeyError):
            pass
    raise SourceError("the map holds no entry for the source value")


def locks(
    role: str,
    forms: Mapping,
    application: Mapping,
    users: Mapping,
    credentials: Mapping,
) -> list[dict[str, Any]]:
    """Return what the shared lock renderer locks in the application's pages.

    Args:
        role: role name.
        forms: ``applications.<role>.forms``.
        application: the rendered ``applications.<role>``; a field's ``when``
            resolves against it.
        users: the rendered global users.
        credentials: the ``credentials`` tree of the role's ``meta/secrets.yml``.

    Returns:
        First one profile lock per form ``page`` path that holds
        ``sso.<claim>`` fields: their ``selector`` parts joined by commas,
        with the ``label`` and ``path`` ``None`` and never ``secret``. Then
        one entry per other ``enforced`` field whose ``when`` holds, in YAML
        order: its form's ``page`` path, its ``selector``, its ``label`` (the
        field key when it declares none), the inventory ``path`` of its value
        and whether the page must hide that value (``secret``), which holds
        for every field the type and path half of the fail-closed rule does
        not clear. A ``seeded`` field yields nothing.

    Raises:
        SourceError: when a ``when`` names nothing in the inventory.
    """
    enforced = [
        (forms[form]["path"], field, spec)
        for form, field, spec in iter_fields(forms)
        if spec.get("mode") == "enforced" and _applies(spec, application, users)
    ]
    profile: dict[str, list[str]] = {}
    for page, _field, spec in enforced:
        if is_sso_source(spec["source"]):
            profile.setdefault(page, []).append(spec["selector"])
    return [
        {
            "page": page,
            "selector": ",".join(selectors),
            "label": None,
            "path": None,
            "secret": False,
        }
        for page, selectors in profile.items()
    ] + [
        {
            "page": page,
            "selector": spec["selector"],
            "label": spec.get("label", field),
            "path": inventory_path(role, spec["source"]),
            "secret": not _plain_field(spec, credentials),
        }
        for page, field, spec in enforced
        if not is_sso_source(spec["source"])
    ]
