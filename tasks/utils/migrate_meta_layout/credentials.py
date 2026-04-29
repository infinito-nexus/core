from __future__ import annotations

from typing import Any, Dict

_SCHEMA_LEAF_KEYS = ("description", "algorithm", "validation", "default")


def detect_collision(
    schema_creds: Dict[str, Any],
    config_creds: Dict[str, Any],
    role_name: str,
) -> None:
    """Raise SystemExit if any path is defined in both schema and config."""

    def _walk(prefix: str, schema_node: Any, config_node: Any) -> None:
        if not isinstance(schema_node, dict) or not isinstance(config_node, dict):
            if prefix:
                _fail(role_name, prefix)
            return
        for key, schema_child in schema_node.items():
            if key not in config_node:
                continue
            next_prefix = f"{prefix}.{key}" if prefix else key
            config_child = config_node[key]
            if isinstance(schema_child, dict) and isinstance(config_child, dict):
                if any(k in schema_child for k in _SCHEMA_LEAF_KEYS):
                    _fail(role_name, next_prefix)
                _walk(next_prefix, schema_child, config_child)
            else:
                _fail(role_name, next_prefix)

    _walk("", schema_creds, config_creds)


def _fail(role_name: str, dotted_path: str) -> None:
    raise SystemExit(
        f"{role_name}: credential key collision at "
        f"credentials.{dotted_path}: present in both schema/main.yml and "
        f"config/main.yml.credentials"
    )


def convert_runtime_to_schema(node: Any) -> Any:
    """Turn `key: '{{ jinja }}'` runtime credentials into schema entries."""
    if not isinstance(node, dict):
        return node
    converted: Dict[str, Any] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            looks_like_schema = any(k in value for k in _SCHEMA_LEAF_KEYS)
            if looks_like_schema:
                if "algorithm" not in value:
                    value = {"algorithm": "plain", **value}
                converted[key] = value
            else:
                converted[key] = convert_runtime_to_schema(value)
        else:
            converted[key] = {
                "description": (
                    f"Runtime credential value imported from config/main.yml "
                    f"for '{key}'."
                ),
                "algorithm": "plain",
                "default": value,
            }
    return converted
