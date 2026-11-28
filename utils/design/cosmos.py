from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.applications.config import get
from utils.roles.applications.topics import provider_of

if TYPE_CHECKING:
    from collections.abc import Mapping

SERVICE_KEY = "cosmos"
DESIGN_PROVIDER = "web-svc-design"
FLAVOR_KEY = "flavor"
FLAVOR_FULL = "full"
FLAVOR_COLORS = "colors"
FLAVORS = (FLAVOR_FULL, FLAVOR_COLORS)
_OFF = frozenset({"false", "no", "off", "0"})
_UNSET = ""


def _setting(applications: Mapping[str, Any], application_id: str, key: str) -> Any:
    return get(
        applications=applications,
        application_id=application_id,
        config_path=f"services.{SERVICE_KEY}.{key}",
        strict=False,
        default=_UNSET,
        skip_missing_app=True,
    )


def _is_off(value: Any) -> bool:
    return value is False or str(value).strip().lower() in _OFF


def _flavor(applications: Mapping[str, Any], application_id: str) -> str:
    value = _setting(applications, application_id, FLAVOR_KEY)
    flavor = value.strip() if isinstance(value, str) else value
    if flavor == _UNSET:
        return _UNSET
    if flavor not in FLAVORS:
        raise ValueError(
            f"{application_id}: services.{SERVICE_KEY}.{FLAVOR_KEY} is {value!r}; "
            f"expected one of {', '.join(FLAVORS)}"
        )
    return flavor


def cosmos_provider(
    applications: Mapping[str, Any],
    application_id: str,
    registry: Mapping[str, Any],
) -> str:
    """
    Args:
        applications: the applications map of the play.
        application_id: the designed role being rendered.
        registry: the service registry of the roles directory.

    Returns:
        The role that provides the ``cosmos`` service while the design role
        enables it and ``application_id`` leaves ``services.cosmos.enabled``
        unset or true; ``""`` otherwise.
    """
    role = provider_of(SERVICE_KEY, registry)
    design_flag = _setting(applications, DESIGN_PROVIDER, "enabled")
    if not role or design_flag == _UNSET or _is_off(design_flag):
        return ""
    if _is_off(_setting(applications, application_id, "enabled")):
        return ""
    return role


def cosmos_flavor(
    applications: Mapping[str, Any],
    application_id: str,
    registry: Mapping[str, Any],
) -> str:
    """
    Args:
        applications: the applications map of the play.
        application_id: the designed role being rendered.
        registry: the service registry of the roles directory.

    Returns:
        ``""`` while :func:`cosmos_provider` returns ``""``; otherwise the
        ``services.cosmos.flavor`` of ``application_id`` when it sets one,
        else the one of the design role. An empty string counts as unset.

    Raises:
        ValueError: ``application_id`` or the design role sets a flavor
            outside ``FLAVORS``, or a provider is active while neither sets
            one; the message names the role and the key.
    """
    own = _flavor(applications, application_id)
    default = _flavor(applications, DESIGN_PROVIDER)
    if not cosmos_provider(applications, application_id, registry):
        return _UNSET
    if not (own or default):
        raise ValueError(
            f"{DESIGN_PROVIDER}: services.{SERVICE_KEY}.{FLAVOR_KEY} is unset; "
            f"expected one of {', '.join(FLAVORS)}"
        )
    return own or default
