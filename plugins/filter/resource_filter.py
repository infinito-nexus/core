from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.applications.config import (
    AppConfigKeyError,
    ConfigEntryNotSetError,
    get,
)
from utils.roles.entity.name import get_entity_name

_UNSET = object()

_CPU_GRANULARITY = 0.01
_FULL_PERCENT = 100


def _is_zero(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    try:
        return float(str(value).strip()) == 0
    except (TypeError, ValueError):
        return False


def resolve_cpus(value, host_cpus):
    """Return the share a percentage names, the value itself otherwise.

    A percentage is read against every CPU the host has, not against the
    fair-share default, so ``100%`` is the whole machine and lands exactly on
    the ceiling docker accepts.

    Args:
        value: the configured ``cpus``, either a plain number as docker takes
            it or a percentage such as ``"50%"``.
        host_cpus: the host's CPU count, normally ``RESOURCE_HOST_CPUS``.

    Raises:
        AnsibleFilterError: the percentage is unreadable or outside 0 to 100,
            or the value is a bare zero, which docker reads as *uncapped*
            rather than as none.
    """
    text = str(value).strip()
    if not text.endswith("%"):
        if _is_zero(value):
            raise AnsibleFilterError(
                f"cpus: {value!r} leaves the container uncapped; "
                "write '100%' to ask for every CPU the host has"
            )
        return value
    try:
        percent = float(text[:-1])
    except ValueError as e:
        raise AnsibleFilterError(f"cpus: {value!r} is not a percentage") from e
    if not 0 <= percent <= _FULL_PERCENT:
        raise AnsibleFilterError(
            f"cpus: {value!r} is outside 0% to 100%; docker refuses more CPUs "
            "than the host has"
        )
    return max(round(float(host_cpus) * percent / _FULL_PERCENT, 2), _CPU_GRANULARITY)


def resource_filter(
    applications: dict,
    application_id: str,
    key: str,
    service_name: str,
    hard_default,
    host_cpus=None,
):
    """
    Lookup order:
      1) services.<service_name or get_entity_name(application_id)>.<key>
      2) services.<get_entity_name(application_id)>.<key>
      3) hard_default (mandatory)

    - service_name may be "" → will resolve to get_entity_name(application_id).
    - hard_default is mandatory (no implicit None).
    - required=False always.
    - host_cpus, when given, resolves a percentage through
      :func:`resolve_cpus`. Callers reading ``cpus`` pass RESOURCE_HOST_CPUS
      so that ``cpus: 50%`` in services.yml means half of the host.
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
    resolved = hard_default if value is _UNSET else value
    if host_cpus is not None:
        return resolve_cpus(resolved, host_cpus)
    return resolved


class FilterModule:
    def filters(self):
        return {
            "resource_filter": resource_filter,
        }
