from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from utils.roles.applications.forms import (
    _PATH,
    MAP_SCALARS,
    MODES,
    _holds_template,
    when_path,
)
from utils.roles.mapping import ROLE_FILE_META_FORMS

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
FORM_KEYS = frozenset({"path", "fields", "sinks", "record"})
RECORD_KEYS = ("selector", "source")
REQUIRED_FIELD_KEYS = ("source", "mode", "selector")
OPTIONAL_FIELD_KEYS = frozenset(
    {"when", "label", "type", "enum", "validation", "description", "map"}
)

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_SINK = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _record_errors(where: str, record: Any) -> list[str]:
    if not (
        isinstance(record, Mapping)
        and set(record) == set(RECORD_KEYS)
        and _non_empty_string(record["selector"])
        and isinstance(record["source"], str)
        and _PATH.fullmatch(record["source"])
    ):
        return [
            (
                f"{where}.record must map selector to the input that shows the"
                " edited record's id and source to the inventory path of the ids"
                " the deployment created"
            )
        ]
    return _template_errors(f"{where}.record", record, iter(RECORD_KEYS))


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
    if "record" in block:
        errors.extend(_record_errors(where, block["record"]))
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
