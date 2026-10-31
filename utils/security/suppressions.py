"""CVE suppressions a role declares in its ``meta/services.yml``.

Each service entry MAY carry::

    <service>:
      security:
        suppressions:
          # nocheck: cve <reason>
          - id: CVE-2026-1234
            until: 2026-12-31
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

RULE = "cve"
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
ENTRY_KEYS = frozenset({"id", "until"})


class SuppressionError(ValueError):
    """A ``security.suppressions`` entry that does not follow the format."""


@dataclass(frozen=True)
class Suppression:
    """One accepted CVE of one service.

    Args:
        id: the ``CVE-YYYY-NNNN`` id.
        until: the last day the suppression applies.
    """

    id: str
    until: dt.date

    def as_json(self) -> dict[str, str]:
        return {"id": self.id, "until": self.until.isoformat()}


def _until(value: Any, where: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise SuppressionError(f"{where}: until must be a date, not a timestamp")
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise SuppressionError(
                f"{where}: until {value!r} is no YYYY-MM-DD date"
            ) from exc
    raise SuppressionError(f"{where}: until is required and must be a YYYY-MM-DD date")


def parse_entries(entries: Any, where: str) -> list[Suppression]:
    """Validate the ``security.suppressions`` list of one service.

    Args:
        entries: the raw list.
        where: ``<role>:<service>`` for the error message.

    Returns:
        The suppressions in declaration order.

    Raises:
        SuppressionError: the list or one of its entries is malformed.
    """
    if not isinstance(entries, list):
        raise SuppressionError(f"{where}: security.suppressions must be a list")
    parsed = []
    for index, entry in enumerate(entries):
        label = f"{where} suppression #{index}"
        if not isinstance(entry, Mapping):
            raise SuppressionError(f"{label}: must be a mapping with id and until")
        unknown = sorted(set(entry) - ENTRY_KEYS)
        if unknown:
            raise SuppressionError(f"{label}: unknown key(s) {', '.join(unknown)}")
        cve = entry.get("id")
        if not isinstance(cve, str) or not CVE_PATTERN.match(cve):
            raise SuppressionError(f"{label}: id {cve!r} is no CVE-YYYY-NNNN id")
        parsed.append(Suppression(id=cve, until=_until(entry.get("until"), label)))
    return parsed


def service_suppressions(services: Any, role: str) -> dict[str, list[Suppression]]:
    """Return the suppressions of every service of one role.

    Args:
        services: the role's ``meta/services.yml`` mapping.
        role: the role id, for error messages.

    Returns:
        ``{service: [Suppression, ...]}`` for each service that declares
        ``security.suppressions``.

    Raises:
        SuppressionError: a declared list is malformed.
    """
    if not isinstance(services, Mapping):
        return {}
    found: dict[str, list[Suppression]] = {}
    for service, spec in services.items():
        if not isinstance(spec, Mapping):
            continue
        security = spec.get("security")
        if security is None:
            continue
        if not isinstance(security, Mapping) or "suppressions" not in security:
            raise SuppressionError(f"{role}:{service}: security must hold suppressions")
        found[str(service)] = parse_entries(
            security["suppressions"], f"{role}:{service}"
        )
    return found


def role_suppressions(roles_dir: Path, role: str) -> dict[str, list[Suppression]]:
    """Read :func:`service_suppressions` from a role's ``meta/services.yml``.

    Args:
        roles_dir: the ``roles/`` directory.
        role: the role id.
    """
    path = roles_dir / role / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return {}
    return service_suppressions(load_yaml_any(str(path)), role)
