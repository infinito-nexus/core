from __future__ import annotations

import json
import re
from collections.abc import Mapping

from ansible.errors import AnsibleFilterError

PERMALINK_STRUCTURE = "permalink_structure"
OPTION_NAME = re.compile(r"[A-Za-z0-9_.-]{1,191}")
STRUCTURE_TAG = re.compile(r"%[^/%]+%")
SECRET_NAME = re.compile(
    r"(?:^|[_.-])(?:pass|passwd|password|pwd|secret|token|salt|credentials?)(?:$|[_.-])"
    r"|(?:api|auth|access|license|nonce|private|secret|logged[_-]in)[_-]?key",
    re.IGNORECASE,
)


def _where(name) -> str:
    return f"services.wordpress.options.{name}"


def _secret_path(path: str, key: str, value) -> str | None:
    """Find the first key in an option that names a secret.

    Args:
        path: dotted path of ``value`` inside the options map.
        key: the mapping key ``value`` sits under; empty for a list element.
        value: the option value or one of its nested values.

    Returns:
        The path of the first secret-named key, or None.
    """
    if SECRET_NAME.search(key):
        return path
    if isinstance(value, Mapping):
        children = [(f"{path}.{k}", str(k), v) for k, v in value.items()]
    elif isinstance(value, list):
        children = [(f"{path}[{i}]", "", v) for i, v in enumerate(value)]
    else:
        return None
    for child in children:
        found = _secret_path(*child)
        if found:
            return found
    return None


def wordpress_options_checked(options, owned_elsewhere):
    """Refuse every entry of ``services.wordpress.options`` this path must not carry.

    Args:
        options: WordPress option name mapped to the value the role pins.
        owned_elsewhere: option names another task or addon of the role writes.

    Returns:
        ``options`` unchanged.

    Raises:
        AnsibleFilterError: naming the first refused option.
    """
    if not isinstance(options, Mapping):
        raise AnsibleFilterError(
            f"services.wordpress.options must be a mapping, got {type(options).__name__}"
        )
    structure = options.get(PERMALINK_STRUCTURE)
    if not isinstance(structure, str) or not STRUCTURE_TAG.search(structure):
        raise AnsibleFilterError(
            f"{_where(PERMALINK_STRUCTURE)} must be a string with a structure tag such as "
            "%postname%: WordPress refuses a custom structure without one, and /wp-json "
            "has no rewrite rule under an empty structure"
        )
    for name, value in options.items():
        if not isinstance(name, str) or not OPTION_NAME.fullmatch(name):
            raise AnsibleFilterError(
                f"{_where(name)}: not a WordPress option name "
                "(letters, digits, '_', '.', '-', at most 191 characters)"
            )
        if name in owned_elsewhere:
            raise AnsibleFilterError(
                f"{_where(name)}: the role already writes this option elsewhere; "
                "change the key that owns it instead"
            )
        secret = _secret_path(name, name, value)
        if secret:
            raise AnsibleFilterError(
                f"{_where(name)}: '{secret}' names a secret; this path passes values on "
                "the container exec command line, so secrets belong in meta/secrets.yml"
            )
        if isinstance(value, bool) or not isinstance(value, (str, int, Mapping, list)):
            raise AnsibleFilterError(
                f"{_where(name)}: {value!r} reads back from WordPress as a different "
                "value; write it as a string, an integer, a mapping or a list"
            )
    return options


def wordpress_option_drifted(result) -> bool:
    """Tell whether WordPress stores something other than the pinned value.

    WP-CLI prints the JSON value as its last stdout line, after any PHP
    warning a plugin emits while WordPress loads. WordPress returns a
    top-level scalar as a string, so scalars compare as strings. PHP prints
    an empty array as ``[]``, so an empty mapping compares equal to it.

    Args:
        result: one result of the ``wp option get --format=json`` loop; its
            ``item`` is the ``{key, value}`` pair of the pinned option.

    Returns:
        True when the option is missing or holds a different value.
    """
    if result["rc"] != 0:
        return True
    desired = result["item"]["value"]
    lines = result["stdout"].strip().splitlines()
    try:
        stored = json.loads(lines[-1] if lines else "")
    except ValueError as exc:
        raise AnsibleFilterError(
            f"{_where(result['item']['key'])}: wp option get printed no JSON ({exc})"
        ) from exc
    if isinstance(desired, (Mapping, list)):
        return stored != (desired or [])
    return str(stored) != str(desired)


class FilterModule:
    """Validate and diff the WordPress options the role pins."""

    def filters(self):
        return {
            "wordpress_options_checked": wordpress_options_checked,
            "wordpress_option_drifted": wordpress_option_drifted,
        }
