"""Resolve which container services a role actually renders.

``meta/services.yml`` cannot answer this. It mixes the role's own
services with the shared ones it merely consumes, and the entries that
do describe a container disagree about which fields they carry: some
name the container, some only the image, some neither because the image
is built. No field is a reliable discriminator, so a heuristic over that
file silently drops real containers.

The authority is the role's own templates. Every block that renders a
container opens with ``{% set service_name = ... %}`` before including
``roles/sys-svc-container/templates/base.yml.j2``, with no exception in
the tree, so the assignments are the service list.

Services contributed by shared partials (an embedded database, redis,
the SSO proxy) are rendered by central roles rather than by the role's
own templates and are out of scope here.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ASSIGNMENT = re.compile(r"\{%-?\s*set\s+service_name\s*=\s*(?P<expr>.+?)\s*-?%\}")


def _literal(token: str) -> str | None:
    if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
        return token[1:-1]
    return None


def _resolve(expression: str, role_vars: dict) -> str:
    """Return the service key an assignment yields, or '' when unresolvable.

    Args:
        expression: the right-hand side of the ``set service_name``.
        role_vars: the role's ``vars/main.yml`` mapping.
    """
    expression = expression.strip()
    literal = _literal(expression)
    if literal is not None:
        return literal
    if "~" in expression:
        prefix = _literal(expression.split("~", 1)[0].strip())
        return f"{prefix}*" if prefix else ""
    value = role_vars.get(expression)
    if isinstance(value, str) and "{{" not in value:
        return value
    return ""


def service_keys(role_dir) -> list[str]:
    """Service keys the role's own templates render, in template order.

    Args:
        role_dir: the role directory.
    """
    role_dir = Path(role_dir)
    loaded = load_yaml_any(str(role_dir / ROLE_FILE_VARS_MAIN), default_if_missing={})
    role_vars = loaded if isinstance(loaded, dict) else {}

    keys: list[str] = []
    for path in sorted((role_dir / "templates").rglob("*.j2")):
        for match in _ASSIGNMENT.finditer(read_text(str(path))):
            key = _resolve(match.group("expr"), role_vars)
            if key and key not in keys:
                keys.append(key)
    return keys
