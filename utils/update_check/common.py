from __future__ import annotations

import re

from utils.roles.entity.name import get_entity_name

OK, WARN, FAIL = "✅", "⚠️", "❌"
AREAS = (
    "inventory",
    "volumes",
    "data",
    "images",
    "ports",
    "networks",
    "webserver",
    "certificates",
    "operations",
)
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, level: str, area: str, subject: str, text: str) -> None:
        self.rows.append((level, area, subject, text))


def truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def version(text) -> tuple[int, ...] | None:
    match = _VERSION.match(str(text).strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def compare(running: tuple[int, ...], wanted: tuple[int, ...]) -> int:
    size = min(len(running), len(wanted))
    return (running[:size] > wanted[:size]) - (running[:size] < wanted[:size])


def _is_registry(part: str) -> bool:
    return "." in part or ":" in part or part == "localhost"


def repo(image: str) -> tuple[str, str]:
    reference = image.split("@", 1)[0]
    name, tag = reference, ""
    if ":" in reference.rsplit("/", 1)[-1]:
        name, tag = reference.rsplit(":", 1)
    parts = name.split("/")
    if "mirror" in parts:
        parts = parts[parts.index("mirror") + 1 :]
    if len(parts) > 1 and _is_registry(parts[0]):
        parts = parts[1:]
    if len(parts) > 1 and parts[0] == "library":
        parts = parts[1:]
    return "/".join(parts).removesuffix("_custom"), tag


def owner(container: str, applications, apps) -> str | None:
    lowered = container.lower()
    for app in apps:
        names = {str(s.get("name") or k) for k, s in services(app, applications[app])}
        if container in names:
            return app
    matches = [
        app
        for app in apps
        if (entity := get_entity_name(app)) and entity.lower() in lowered
    ]
    return max(matches, key=lambda app: len(get_entity_name(app)), default=None)


def services(application_id: str, application: dict):
    """A shared service other than the primary one is provided by another role."""
    entity = get_entity_name(application_id)
    for key, service in (application.get("services") or {}).items():
        if not isinstance(service, dict) or not truthy(service.get("enabled", True)):
            continue
        if key != entity and truthy(service.get("shared")):
            continue
        yield key, service


def pinned(application_id: str, application: dict):
    for key, service in services(application_id, application):
        if service.get("image") and service.get("version"):
            yield key, service
