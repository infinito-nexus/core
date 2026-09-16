"""Proprietary API credential SPOT, read from group_vars/all/18_api.yml.

``API`` is a plain mapping, so an inventory that configures three providers
replaces the whole declaration instead of merging into it, and every provider it
does not name disappears. Resolving a hidden provider then raises, and a raising
lookup inside a value the applications renderer is templating leaves the raw
``{{ ... }}`` text in place: the consumer stores template text, and ``| bool``
coerces it to False with a deprecation warning that fails the deploy on the
warning gate.

Merging the scope's override over the declared defaults keeps every declared
provider resolvable, so an override narrows values, never the provider set.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from utils import PROJECT_ROOT
from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any

_API_SPOT_FILE = str(PROJECT_ROOT / "group_vars" / "all" / "18_api.yml")


def declared_api() -> dict[str, Any]:
    """The ``API`` mapping as declared in the group_vars SPOT.

    Returns:
        Provider name to credential mapping, every value a plain string.

    Raises:
        TypeError: the SPOT does not declare ``API`` as a mapping.
    """
    document = load_yaml_any(_API_SPOT_FILE, default_if_missing={}) or {}
    declared = document.get("API") if isinstance(document, Mapping) else None
    if not isinstance(declared, Mapping):
        raise TypeError(f"{_API_SPOT_FILE} does not declare 'API' as a mapping.")
    return dict(declared)


def resolve_api(
    variables: Mapping[str, Any] | None, templar: Any = None
) -> dict[str, Any]:
    """The effective ``API`` mapping for a render scope.

    Args:
        variables: the scope's variables; its ``API`` entry overrides the SPOT.
        templar: optional templar; renders the override and the merged values,
            so an inventory may source a credential from an env lookup.

    Returns:
        The SPOT declaration with the scope's override merged over it.

    Raises:
        TypeError: the scope's ``API`` is present but not a mapping.
    """
    declared = declared_api()
    override: Any = (variables or {}).get("API")
    if override is not None and not isinstance(override, Mapping) and templar:
        override = _templated(templar, override)
    if override is None:
        return declared
    if not isinstance(override, Mapping):
        raise TypeError("'API' is defined but is not a mapping.")
    merged = _deep_merge(declared, dict(override))
    if templar is None:
        return merged
    rendered = _templated(templar, merged)
    return dict(rendered) if isinstance(rendered, Mapping) else merged


def _templated(templar: Any, value: Any) -> Any:
    from ansible.errors import AnsibleError

    try:
        return templar.template(value, fail_on_undefined=False)
    except TypeError:
        pass
    except (AnsibleError, ValueError):
        return value

    try:
        return templar.template(value)
    except (AnsibleError, TypeError, ValueError):
        return value


def provider_enabled(api: Mapping[str, Any], provider: str) -> bool:
    """Whether every credential of a provider carries a value.

    Args:
        api: an effective ``API`` mapping, as returned by ``resolve_api``.
        provider: the provider name, e.g. ``github``.

    Returns:
        True when the provider declares at least one credential and none of
        them is empty.

    Raises:
        KeyError: the provider is not declared in the SPOT.
    """
    credentials = api.get(provider)
    if not isinstance(credentials, Mapping):
        raise KeyError(
            f"unknown API provider {provider!r}; declare it under 'API' in "
            f"{_API_SPOT_FILE}."
        )
    if not credentials:
        return False
    return all(str(value).strip() for value in credentials.values())
