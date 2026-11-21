from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime

EVENT_COLLECTION = "community.lexicon.calendar.event"
TOKEN_PREFIX = f"{EVENT_COLLECTION}#"
URI_LOCATION = f"{EVENT_COLLECTION}#uri"
ADDRESS_LOCATION = "community.lexicon.location.address"
GEO_LOCATIONS = ("community.lexicon.location.geo", "community.lexicon.location.fsq")

STATUS_DEFAULT = "scheduled"
MODE_DEFAULT = "inperson"
STATUSES = {
    "scheduled": "CONFIRMED",
    "rescheduled": "CONFIRMED",
    "planned": "TENTATIVE",
    "postponed": "TENTATIVE",
    "cancelled": "CANCELLED",
}
MODES = ("inperson", "virtual", "hybrid")
MAPPED_FIELDS = frozenset(
    {
        "$type",
        "name",
        "description",
        "startsAt",
        "endsAt",
        "status",
        "mode",
        "locations",
        "uris",
    }
)
ADDRESS_FIELDS = (
    ("street", "street"),
    ("locality", "locality"),
    ("postalCode", "postalCode"),
    ("region", "region"),
    ("country", "country"),
    ("name", "description"),
)


class UnmappableError(ValueError):
    pass


@dataclass(frozen=True)
class MappedEvent:
    payload: dict
    unmapped: list = field(default_factory=list)


def split_at_uri(at_uri: str) -> tuple[str, str, str]:
    prefix = "at://"
    parts = at_uri[len(prefix) :].split("/") if at_uri.startswith(prefix) else []
    if len(parts) != 3 or not all(parts):
        raise UnmappableError(
            f"{at_uri!r} is not an at://<did>/<collection>/<rkey> URI"
        )
    return parts[0], parts[1], parts[2]


def _token(record: dict, key: str, known, lexicon_default: str) -> str:
    value = record.get(key)
    if value is None:
        return lexicon_default
    name = (
        value[len(TOKEN_PREFIX) :]
        if isinstance(value, str) and value.startswith(TOKEN_PREFIX)
        else None
    )
    if name not in known:
        raise UnmappableError(
            f"{key} {value!r} is not a known {EVENT_COLLECTION} value"
        )
    return name


def _timestamp(value, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnmappableError(f"{key} is missing")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise UnmappableError(f"{key} {value!r} is not an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise UnmappableError(f"{key} {value!r} carries no UTC offset")
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first(locations: list, types, consumed: set) -> dict | None:
    for index, location in enumerate(locations):
        if isinstance(location, dict) and location.get("$type") in types:
            consumed.add(index)
            return location
    return None


def _physical_address(locations: list, consumed: set) -> dict | None:
    address = _first(locations, (ADDRESS_LOCATION,), consumed)
    geo = _first(locations, GEO_LOCATIONS, consumed)
    result = {}
    for source, target in ADDRESS_FIELDS:
        if address and str(address.get(source, "")).strip():
            result[target] = str(address[source]).strip()
    if geo and geo.get("latitude") and geo.get("longitude"):
        try:
            result["geom"] = f"{float(geo['longitude'])};{float(geo['latitude'])}"
        except ValueError as exc:
            raise UnmappableError(
                f"geo location {geo!r} carries no numeric coordinates"
            ) from exc
        if "description" not in result and str(geo.get("name", "")).strip():
            result["description"] = str(geo["name"]).strip()
    return result or None


def _description(record: dict, event_url: str) -> str:
    text = str(record.get("description") or "")
    blocks = [
        "<p>" + html.escape(block.strip()).replace("\n", "<br>") + "</p>"
        for block in text.split("\n\n")
        if block.strip()
    ]
    links = [event_url]
    links.extend(
        str(item["uri"]).strip()
        for item in record.get("uris") or []
        if isinstance(item, dict) and str(item.get("uri", "")).strip()
    )
    for link in links:
        escaped = html.escape(link, quote=True)
        blocks.append(f'<p><a href="{escaped}">{escaped}</a></p>')
    return "".join(blocks)


def event_url(appview_url: str, at_uri: str) -> str:
    did, _collection, rkey = split_at_uri(at_uri)
    return f"{appview_url.rstrip('/')}/p/{did}/e/{rkey}"


def map_event(record: dict, at_uri: str, appview_url: str) -> MappedEvent:
    """Translate a calendar event record into Mobilizon event arguments.

    Args:
        record: the ``community.lexicon.calendar.event`` record value.
        at_uri: the record's ``at://`` URI, linked back from the description.
        appview_url: base URL of the atmo appview the link points at.

    Returns:
        The Mobilizon mutation arguments and the record fields no argument
        carries, so the caller can report them.
    """
    if not isinstance(record, dict):
        raise UnmappableError("record is not an object")
    title = str(record.get("name") or "").strip()
    if not title:
        raise UnmappableError("name is missing")
    begins_on = _timestamp(record.get("startsAt"), "startsAt")
    ends_on = _timestamp(record["endsAt"], "endsAt") if record.get("endsAt") else None
    if ends_on is not None and ends_on < begins_on:
        raise UnmappableError("endsAt lies before startsAt")
    status = _token(record, "status", STATUSES, STATUS_DEFAULT)
    mode = _token(record, "mode", MODES, MODE_DEFAULT)
    locations = [
        item for item in record.get("locations") or [] if isinstance(item, dict)
    ]
    consumed: set = set()
    physical = (
        _physical_address(locations, consumed)
        if mode in ("inperson", "hybrid")
        else None
    )
    online = None
    if mode in ("virtual", "hybrid"):
        uri_location = _first(locations, (URI_LOCATION,), consumed)
        online = str(uri_location.get("uri", "")).strip() if uri_location else None
    payload = {
        "title": title,
        "description": _description(record, event_url(appview_url, at_uri)),
        "beginsOn": begins_on,
        "endsOn": ends_on,
        "status": STATUSES[status],
        "visibility": "PUBLIC",
        "draft": False,
        "onlineAddress": online or None,
        "physicalAddress": physical,
    }
    unmapped = sorted(key for key in record if key not in MAPPED_FIELDS)
    unmapped += [
        f"locations[{index}]:{location.get('$type', 'untyped')}"
        for index, location in enumerate(locations)
        if index not in consumed
    ]
    return MappedEvent(payload=payload, unmapped=unmapped)
