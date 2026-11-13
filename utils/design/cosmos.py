from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.applications.config import get
from utils.roles.applications.topics import provider_of

if TYPE_CHECKING:
    from collections.abc import Mapping

SERVICE_KEY = "cosmos"
DESIGN_PROVIDER = "web-svc-design"
_OFF = frozenset({"false", "no", "off", "0"})
_UNSET = ""


def _enabled_flag(applications: Mapping[str, Any], application_id: str) -> Any:
    return get(
        applications=applications,
        application_id=application_id,
        config_path=f"services.{SERVICE_KEY}.enabled",
        strict=False,
        default=_UNSET,
        skip_missing_app=True,
    )


def _is_off(value: Any) -> bool:
    return value is False or str(value).strip().lower() in _OFF


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
    design_flag = _enabled_flag(applications, DESIGN_PROVIDER)
    if not role or design_flag == _UNSET or _is_off(design_flag):
        return ""
    if _is_off(_enabled_flag(applications, application_id)):
        return ""
    return role
