from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.applications.config import (
    AppConfigKeyError,
    ConfigEntryNotSetError,
    get,
)
from utils.roles.entity_name import get_entity_name


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
      2) hard_default (mandatory)

    - service_name may be "" → will resolve to get_entity_name(application_id).
    - hard_default is mandatory (no implicit None).
    - required=False always.
    """
    try:
        primary_service = (
            service_name if service_name != "" else get_entity_name(application_id)
        )
        return get(
            applications,
            application_id,
            f"services.{primary_service}.{key}",
            False,
            hard_default,
        )
    except (AppConfigKeyError, ConfigEntryNotSetError) as e:
        raise AnsibleFilterError(str(e)) from e


class FilterModule:
    def filters(self):
        return {
            "resource_filter": resource_filter,
        }
