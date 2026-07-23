from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.applications.config import (
    AppConfigKeyError,
    ConfigEntryNotSetError,
    get,
)
from utils.roles.entity.name import get_entity_name

_UNSET = object()


def resource_filter(
    applications: dict,
    application_id: str,
    key: str,
    service_name: str,
    hard_default,
):
    """
    Lookup order:
      1) services.<service_name or get_entity_name(application_id)>.<key>
      2) services.<get_entity_name(application_id)>.<key>
      3) hard_default (mandatory)

    - service_name may be "" → will resolve to get_entity_name(application_id).
    - hard_default is mandatory (no implicit None).
    - required=False always.
    """
    try:
        entity = get_entity_name(application_id)
        primary_service = service_name if service_name != "" else entity
        value = _UNSET
        for candidate in dict.fromkeys([primary_service, entity]):
            value = get(
                applications,
                application_id,
                f"services.{candidate}.{key}",
                False,
                _UNSET,
            )
            if value is not _UNSET:
                break
    except (AppConfigKeyError, ConfigEntryNotSetError) as e:
        raise AnsibleFilterError(str(e)) from e
    return hard_default if value is _UNSET else value


class FilterModule:
    def filters(self):
        return {
            "resource_filter": resource_filter,
        }
