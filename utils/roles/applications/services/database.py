from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

RDBMS_SERVICE_KEYS = ("mariadb", "postgres")


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get_compose_services(
    applications: Mapping[str, Any],
    application_id: str,
) -> dict[str, Any]:
    """Return the role's services map.

    The materialised application payload exposes services under the
    bare ``services`` key (no ``compose.services`` wrapper). The
    function name is preserved for backwards compatibility with
    existing call sites.
    """
    application = _as_mapping(applications.get(application_id))
    return _as_mapping(application.get("services"))


def get_database_service_config(
    applications: Mapping[str, Any],
    application_id: str,
) -> dict[str, Any]:
    service_key = resolve_database_service_key(applications, application_id)
    if not service_key:
        return {}
    return _as_mapping(
        get_compose_services(applications, application_id).get(service_key)
    )


def resolve_database_service_key(
    applications: Mapping[str, Any],
    application_id: str,
) -> str:
    services = get_compose_services(applications, application_id)
    enabled_keys = [
        service_key
        for service_key in RDBMS_SERVICE_KEYS
        if _as_mapping(services.get(service_key)).get("enabled") is True
    ]

    if len(enabled_keys) > 1:
        raise ValueError(
            f"{application_id}: multiple direct database services are enabled: "
            + ", ".join(enabled_keys)
        )

    return enabled_keys[0] if enabled_keys else ""


def has_single_database_service(
    applications: Mapping[str, Any],
    application_id: str,
) -> bool:
    services = get_compose_services(applications, application_id)
    enabled_count = sum(
        1
        for service_key in RDBMS_SERVICE_KEYS
        if _as_mapping(services.get(service_key)).get("enabled") is True
    )
    return enabled_count == 1
