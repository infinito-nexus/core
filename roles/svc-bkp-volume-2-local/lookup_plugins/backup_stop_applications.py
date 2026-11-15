from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

_OFF = frozenset({"false", "no", "0", "off", ""})


def _switched_off(value: Any) -> bool:
    """
    Args:
        value: a rendered ``services.<key>.enabled`` flag, None when absent.

    Returns:
        True only for a flag that states the service is off.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return not value
    return str(value).strip().lower() in _OFF


def _stops_for_backup(svc: Any) -> bool:
    """
    Args:
        svc: one ``services.<key>`` entry.

    Returns:
        True when the entry runs a container of its own that declares
        ``backup.stop_required: true`` and is not switched off.
    """
    if not isinstance(svc, Mapping):
        return False
    backup = svc.get("backup")
    if not isinstance(backup, Mapping) or backup.get("stop_required") is not True:
        return False
    if not (svc.get("image") or svc.get("custom")):
        return False
    return not _switched_off(svc.get("enabled"))


def stop_applications(
    applications: Mapping[str, Any], deployed: list[str] | tuple[str, ...]
) -> list[str]:
    """
    Args:
        applications: the merged ``applications`` config.
        deployed: the application ids of this host, its ``group_names``.

    Returns:
        The sorted ids of the deployed applications with a service that
        carries an image or is custom-built and declares
        ``backup.stop_required: true``.
    """
    found: set[str] = set()
    for application_id, app in applications.items():
        if application_id not in deployed or not isinstance(app, Mapping):
            continue
        services = app.get("services")
        if not isinstance(services, Mapping):
            continue
        if any(_stops_for_backup(svc) for svc in services.values()):
            found.add(str(application_id))
    return sorted(found)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        """
        Args:
            terms: none.
            variables: the play variables; ``group_names`` names the
                applications of this host.

        Returns:
            One list: the ids a live backup copy stops, for the maintenance
            signal of the backup unit.
        """
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]
        deployed = vars_.get("group_names")
        if not isinstance(deployed, (list, tuple)):
            raise AnsibleError(
                "backup_stop_applications needs group_names to tell the "
                "applications of this host"
            )
        if not isinstance(applications, Mapping):
            return [[]]
        return [stop_applications(applications, list(deployed))]
