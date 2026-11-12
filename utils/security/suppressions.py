"""CVE suppressions a role declares in its ``meta/services.yml``.

Each service entry MAY carry::

    <service>:
      security:
        suppressions:
          # nocheck: cve <reason>
          - id: CVE-2026-1234
            until: 2026-12-31
          # nocheck: cve <reason>
          - image_tag: "2.18.5"
            until: 2026-12-31

An ``id`` entry accepts one CVE, an ``image_tag`` entry every finding of the
service's image while it runs that tag.
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
ENTRY_KEYS = frozenset({"id", "image_tag", "until"})
SUBJECT_KEYS = ("id", "image_tag")


class SuppressionError(ValueError):
    """A ``security.suppressions`` entry that does not follow the format."""


@dataclass(frozen=True)
class Suppression:
    """One accepted CVE, or every finding of one image tag, of one service.

    Args:
        id: the ``CVE-YYYY-NNNN`` id, ``None`` for an image tag entry.
        image_tag: the image tag, ``None`` for a CVE entry.
        until: the last day the suppression applies.
    """

    id: str | None
    image_tag: str | None
    until: dt.date

    @property
    def subject(self) -> str:
        return self.id or f"image tag {self.image_tag}"

    def as_json(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "image_tag": self.image_tag,
            "until": self.until.isoformat(),
        }


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
            raise SuppressionError(
                f"{label}: must be a mapping with id or image_tag and until"
            )
        unknown = sorted(set(entry) - ENTRY_KEYS)
        if unknown:
            raise SuppressionError(f"{label}: unknown key(s) {', '.join(unknown)}")
        subjects = [key for key in SUBJECT_KEYS if key in entry]
        if len(subjects) != 1:
            raise SuppressionError(f"{label}: needs exactly one of id and image_tag")
        cve = entry.get("id")
        tag = entry.get("image_tag")
        if "id" in entry and (not isinstance(cve, str) or not CVE_PATTERN.match(cve)):
            raise SuppressionError(f"{label}: id {cve!r} is no CVE-YYYY-NNNN id")
        if "image_tag" in entry and (not isinstance(tag, str) or not tag):
            raise SuppressionError(
                f"{label}: image_tag {tag!r} must be a non-empty quoted string"
            )
        parsed.append(
            Suppression(id=cve, image_tag=tag, until=_until(entry.get("until"), label))
        )
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


IMAGE_TAG_KEY = re.compile(r"^\s*(?:-\s+)?image_tag\s*:")


def _blank(line: str) -> bool:
    return not line.strip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _item(line: str, indent: int) -> bool:
    return _indent(line) == indent and line.lstrip().startswith("-")


def _span_end(lines: list[str], index: int) -> int:
    """Return the index after the last line of the value under the key at *index*.

    A sequence written at the key's own indent belongs to the value too, with
    the comments directly above its items.
    """
    key = _indent(lines[index])
    end = index + 1
    cursor = index + 1
    while cursor < len(lines):
        line = lines[cursor]
        if _blank(line):
            cursor += 1
            continue
        if _indent(line) > key or _item(line, key):
            cursor += 1
            end = cursor
            continue
        ahead = cursor
        while ahead < len(lines) and (
            _blank(lines[ahead]) or lines[ahead].lstrip().startswith("#")
        ):
            ahead += 1
        if ahead < len(lines) and _item(lines[ahead], key):
            cursor = ahead
            continue
        break
    return end


def _kept_entries(region: list[str]) -> list[str]:
    """Return the list *region* without its ``image_tag`` entries and their markers."""
    starts = [line for line in region if line.lstrip().startswith("-")]
    if not starts:
        return region
    item_indent = min(_indent(line) for line in starts)
    groups: list[list[str]] = []
    pending: list[str] = []
    for line in region:
        if _item(line, item_indent):
            groups.append([*pending, line])
            pending = []
        elif groups and not (
            line.lstrip().startswith("#") and _indent(line) <= item_indent
        ):
            groups[-1].append(line)
        else:
            pending.append(line)
    kept = [
        line
        for group in groups
        if not any(IMAGE_TAG_KEY.match(line) for line in group)
        for line in group
    ]
    return [*kept, *pending]


def _drop_in_body(body: list[str]) -> list[str]:
    content = [line for line in body if not _blank(line)]
    if not content:
        return body
    child = min(_indent(line) for line in content)
    security = next(
        (
            index
            for index, line in enumerate(body)
            if _indent(line) == child and re.match(r"^\s*security\s*:\s*$", line)
        ),
        None,
    )
    if security is None:
        return body
    security_end = _span_end(body, security)
    listing = next(
        (
            index
            for index in range(security + 1, security_end)
            if re.match(r"^\s*suppressions\s*:\s*$", body[index])
        ),
        None,
    )
    if listing is None:
        return body
    listing_end = _span_end(body, listing)
    kept = _kept_entries(body[listing + 1 : listing_end])
    if any(not _blank(line) and not line.lstrip().startswith("#") for line in kept):
        return [*body[: listing + 1], *kept, *body[listing_end:]]
    body = [*body[:listing], *body[listing_end:]]
    security_end = _span_end(body, security)
    if all(_blank(line) for line in body[security + 1 : security_end]):
        body = [*body[:security], *body[security_end:]]
    return body


def drop_image_tag_entries(lines: list[str], service: str) -> list[str]:
    """Remove the ``image_tag`` suppressions of one top-level service.

    The image updater calls this when it moves the service to another
    version, so a tag suppression never outlives its tag. Each entry leaves
    with the marker comments above it; a list left empty takes its
    ``suppressions:`` key along, and a ``security:`` key left empty its own.

    Args:
        lines: the lines of a ``meta/services.yml``, line endings kept.
        service: the top-level service key.

    Returns:
        The lines without those entries; *lines* itself when there are none.
    """
    header = re.compile(rf"^{re.escape(service)}\s*:")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return lines
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if not _blank(lines[index]) and _indent(lines[index]) == 0
        ),
        len(lines),
    )
    body = _drop_in_body(lines[start + 1 : end])
    return [*lines[: start + 1], *body, *lines[end:]]
