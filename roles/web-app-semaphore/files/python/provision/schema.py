from __future__ import annotations

import re

KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "pattern",
        "required",
        "properties",
        "additionalProperties",
        "propertyNames",
        "minProperties",
    }
)
ANNOTATIONS = frozenset({"$schema", "title", "description", "$defs", "outputs"})
TYPES = {
    "object": dict,
    "string": str,
    "boolean": bool,
    "integer": int,
    "array": list,
}


class SchemaError(ValueError):
    """Args:
    path: the dotted key path of the offending value, empty for the root.
    reason: the rule the value breaks.
    """

    def __init__(self, path, reason):
        super().__init__(f"{path or '<root>'}: {reason}")
        self.path = path
        self.reason = reason


def _join(path, key):
    return f"{path}.{key}" if path else str(key)


def _is(value, kind):
    if kind not in TYPES:
        raise SchemaError("", f"unsupported type {kind}")
    if isinstance(value, bool) and kind != "boolean":
        return False
    return isinstance(value, TYPES[kind])


def _check_object(document, schema, path):
    for name in schema.get("required", []):
        if name not in document:
            raise SchemaError(_join(path, name), "is missing")
    if len(document) < schema.get("minProperties", 0):
        raise SchemaError(path, f"holds fewer than {schema['minProperties']} keys")
    properties = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for key, value in document.items():
        if "propertyNames" in schema:
            check(key, schema["propertyNames"], _join(path, key))
        if key in properties:
            check(value, properties[key], _join(path, key))
        elif extra is False:
            raise SchemaError(_join(path, key), "is not a known key")
        elif isinstance(extra, dict):
            check(value, extra, _join(path, key))


def check(document, schema, path=""):
    """Args:
        document: the decoded JSON value.
        schema: a schema of ``KEYWORDS`` and ``ANNOTATIONS``; any other
            keyword raises.
        path: the key path of ``document``, empty for the root.

    Returns:
        None; the first broken rule raises :class:`SchemaError`.
    """
    unknown = sorted(set(schema) - KEYWORDS - ANNOTATIONS)
    if unknown:
        raise SchemaError(path, f"schema uses unsupported keywords {unknown}")
    kind = schema.get("type")
    if kind is not None and not _is(document, kind):
        raise SchemaError(path, f"is not of type {kind}")
    if "enum" in schema and document not in schema["enum"]:
        raise SchemaError(path, f"is not one of {schema['enum']}")
    if "pattern" in schema and not (
        isinstance(document, str) and re.fullmatch(schema["pattern"], document)
    ):
        raise SchemaError(path, f"does not match {schema['pattern']}")
    if isinstance(document, dict):
        _check_object(document, schema, path)


def definition(interface, name):
    """Args:
        interface: the decoded ``interface.json``.
        name: ``inputs`` for the root's variables, else a key of ``$defs``.

    Returns:
        The schema of that name.
    """
    if name == "inputs":
        return {key: value for key, value in interface.items() if key != "$defs"}
    return interface["$defs"][name]
