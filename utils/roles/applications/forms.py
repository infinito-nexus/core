from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from ansible.module_utils.parsing.convert_bool import boolean

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS

if TYPE_CHECKING:
    from pathlib import Path

MODES = ("enforced", "seeded")
LOCK_PENDING = "pending"
NEGATION = "!"
MAP_SCALARS = (str, int, float, bool)
USERS_ROOT = "users"
SSO_ROOT = "sso"
SERVICES_ROOT = "services"
SERVICE_VALUE_START = 2
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

_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


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


def _walk(node: Any, parts: list[str], source: str) -> Any:
    for part in parts:
        if not isinstance(node, Mapping) or part not in node:
            raise SourceError("the source names nothing in the inventory")
        node = node[part]
    return node


def _is_user_path(parts: list[str]) -> bool:
    return parts[0] == USERS_ROOT


def is_sso_source(source: Any) -> bool:
    """Whether a field's ``source`` names an ``OIDC.ATTRIBUTES`` key of the SSO sign-in.

    Args:
        source: the field's ``source``.
    """
    return isinstance(source, str) and source.split(".", 1)[0] == SSO_ROOT


def is_native(block: Any) -> bool:
    """Whether the application locks a form's fields itself.

    Args:
        block: one form of ``meta/forms.yml``.
    """
    return isinstance(block, Mapping) and block.get("native") is True


def is_lock_pending(block: Any) -> bool:
    """Whether no lock reaches a form's fields yet, with the issue that tracks it.

    Args:
        block: one form of ``meta/forms.yml``.
    """
    return (
        isinstance(block, Mapping)
        and block.get("lock") == LOCK_PENDING
        and isinstance(block.get("issue"), str)
        and bool(block["issue"].strip())
    )


def renders_lock(block: Any) -> bool:
    """Whether the shared renderer locks a form's enforced fields.

    Args:
        block: one form of ``meta/forms.yml``.
    """
    return not (is_native(block) or is_lock_pending(block))


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
            a user path of another shape or a refused user attribute, or is
            an ``sso`` source; the message never repeats the source.
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
        ``<form>.<field>.<key>`` or ``<form>.record.source`` coordinate and
        never the path itself; an ``sso.<ATTRIBUTE>`` field source is left to
        ``sso_fields.errors``, while a record source is refused under
        ``users``, ``secrets.credentials`` or ``sso``, with a last segment
        matching ``SECRET_SEGMENT`` or with a segment named like a declared
        credential.
    """
    errors = _record_source_errors(role, forms, application, users, credentials)
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
        ``users`` or ``secrets.credentials``, for a path with a value segment
        that matches ``SECRET_SEGMENT``, and for a path with a segment named
        like a credential the role declares, all case-insensitive. Every
        segment is a value segment except the service name of a
        ``services.<name>.<value>`` path.
    """
    if not (isinstance(source, str) and _PATH.fullmatch(source)):
        return True
    parts = source.split(".")
    return _secret_path(parts, credentials, _value_segments(parts))


def _value_segments(parts: list[str]) -> list[str]:
    if parts[0] == SERVICES_ROOT and len(parts) > SERVICE_VALUE_START:
        return parts[SERVICE_VALUE_START:]
    return parts


def _secret_path(parts: list[str], credentials: Mapping, searched: list[str]) -> bool:
    names = {name.lower() for name in _credential_names(credentials)}
    return (
        _is_user_path(parts)
        or _is_credential_source(parts)
        or any(SECRET_SEGMENT.search(part) for part in searched)
        or bool({part.lower() for part in parts} & names)
    )


def _record_source_errors(
    role: str,
    forms: Mapping,
    application: Mapping,
    users: Mapping,
    credentials: Mapping,
) -> list[str]:
    errors = []
    for form, block in forms.items():
        record = block.get("record") if isinstance(block, Mapping) else None
        source = record.get("source") if isinstance(record, Mapping) else None
        if not (isinstance(source, str) and _PATH.fullmatch(source)):
            continue
        where = f"{role}: {form}.record.source"
        parts = source.split(".")
        if is_sso_source(source) or _secret_path(parts, credentials, parts[-1:]):
            errors.append(f"{where} must name no secret; every page carries its ids")
        elif not declares(source, application, users, credentials):
            errors.append(f"{where} names nothing in the inventory")
    return errors


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
    if "when" in spec:
        holds = boolean(
            resolve(when_path(spec["when"]), application, users), strict=False
        )
        if holds == spec["when"].startswith(NEGATION):
            return False
    return not (
        spec.get("optional") is True
        and resolve(spec["source"], application, users) is False
    )


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


def _record(block: Mapping, application: Mapping, users: Mapping) -> dict[str, Any]:
    record = block.get("record")
    if record is None:
        return {}
    ids = resolve(record["source"], application, users)
    if not (isinstance(ids, list) and all(isinstance(entry, str) for entry in ids)):
        raise SourceError("the record source holds no list of record ids")
    return {"record": {"selector": record["selector"], "values": list(ids)}}


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
        ``sso.<ATTRIBUTE>`` fields: their ``selector`` parts joined by commas,
        with the ``label`` and ``path`` ``None`` and never ``secret``. Then
        one entry per other ``enforced`` field whose ``when`` holds and, for
        an ``optional`` field, whose source is not ``false``, in YAML
        order: its form's ``page`` path, its ``selector``, its ``label`` (the
        field key when it declares none), the inventory ``path`` of its value
        and whether the page must hide that value (``secret``), which holds
        for every field the type and path half of the fail-closed rule does
        not clear; a field whose form declares a ``record`` also carries
        that ``record``: its ``selector`` and the ``values`` its ``source``
        holds, the ids of the records the deployment created. A ``seeded``
        field, a field of a ``native`` form, which the application locks
        itself, and a field of a ``lock: pending`` form, which no lock
        reaches yet, yield nothing.

    Raises:
        SourceError: when a ``when``, the ``source`` of an ``optional`` field
            or a record ``source`` names nothing in the inventory, or the
            record ids are no list of strings.
    """
    enforced = [
        (form, forms[form]["path"], field, spec)
        for form, field, spec in iter_fields(forms)
        if spec.get("mode") == "enforced"
        and renders_lock(forms[form])
        and _applies(spec, application, users)
    ]
    profile: dict[str, list[str]] = {}
    for _form, page, _field, spec in enforced:
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
            **_record(forms[form], application, users),
        }
        for form, page, field, spec in enforced
        if not is_sso_source(spec["source"])
    ]
