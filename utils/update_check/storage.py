from __future__ import annotations

import re
from collections import defaultdict

from utils.cache.yaml import load_yaml_str
from utils.roles.entity.name import get_entity_name
from utils.update_check.common import (
    FAIL,
    OK,
    WARN,
    compare,
    owner,
    pinned,
    repo,
    services,
    version,
)

ENGINES = {
    "PG_VERSION": ("postgres", "postgis"),
    "mysql_upgrade_info": ("mariadb", "mysql"),
    "version.php": ("nextcloud",),
}
_ANONYMOUS_VOLUME = re.compile(r"^[0-9a-f]{64}$")


def _renamed(name: str, orphan: str, entity: str) -> bool:
    new, old = name.lower().replace("-", "_"), orphan.lower().replace("-", "_")
    if new == old:
        return True
    stem = new.rsplit("_", 1)[0]
    return "_" in new and stem != entity.lower() and old.rsplit("_", 1)[0] == stem


def expected_volumes(report, applications, compose_volumes, deployed) -> dict[str, str]:
    expected = {}
    for app in deployed:
        rendered = compose_volumes.get(app)
        if not rendered:
            report.add(
                WARN,
                "volumes",
                app,
                "compose_volumes did not resolve, its volumes are unchecked",
            )
            continue
        meta = applications[app].get("volumes") or {}
        entity = get_entity_name(app)
        for key, spec in ((load_yaml_str(rendered) or {}).get("volumes") or {}).items():
            declared = meta.get(key)
            if isinstance(declared, dict) and not (
                declared.get("mounts") or declared.get("name")
            ):
                continue
            expected[str((spec or {}).get("name") or f"{entity}_{key}")] = app
    return expected


def volumes(report, applications, group_names, records, expected):
    actual = {fields[0]: fields[1] for fields in records["volume"] if len(fields) > 1}
    mass = None
    if "svc-opt-ssd-hdd" in group_names:
        mass = (
            (applications["svc-opt-ssd-hdd"].get("volumes") or {})
            .get("mass_storage", {})
            .get("path")
        )
    orphans = sorted(
        name
        for name in actual
        if name not in expected and not _ANONYMOUS_VOLUME.match(name)
    )
    for name, app in sorted(expected.items()):
        if name not in actual:
            entity = get_entity_name(app)
            lookalikes = [o for o in orphans if _renamed(name, o, entity)]
            if lookalikes:
                report.add(
                    FAIL,
                    "volumes",
                    name,
                    f"missing for {app}, while {', '.join(lookalikes)} exists: copy its data or accept an empty start",
                )
            else:
                report.add(
                    WARN,
                    "volumes",
                    name,
                    f"missing for {app}: the deploy creates it empty",
                )
            continue
        path = actual[name]
        on_mass = bool(mass) and path.startswith(str(mass).rstrip("/") + "/")
        if on_mass and app.startswith("svc-db-"):
            report.add(
                WARN,
                "volumes",
                name,
                f"database volume of {app} on mass storage ({path})",
            )
        else:
            report.add(OK, "volumes", name, f"{app}, {path}")
    for name in orphans:
        report.add(
            WARN, "volumes", name, f"no deployed role declares it ({actual[name]})"
        )


def data(report, applications, records, expected):
    actual = sorted(
        (
            (fields[1].rstrip("/") + "/", fields[0])
            for fields in records["volume"]
            if len(fields) > 1
        ),
        key=lambda item: -len(item[0]),
    )
    for fields in records["dataversion"]:
        if len(fields) < 2 or not fields[1].strip():
            continue
        path, value = fields[0], fields[1].strip()
        kind = path.rsplit("/", 1)[-1]
        volume = next((name for prefix, name in actual if path.startswith(prefix)), "")
        app = expected.get(volume)
        found = version(value)
        if not app or found is None:
            report.add(
                WARN,
                "data",
                path,
                f"{value}: no deployed role owns volume {volume or '?'}",
            )
            continue
        engines = ENGINES[kind]
        wanted = [
            (service.get("version"), version(service.get("version")))
            for _, service in services(app, applications[app])
            if repo(str(service.get("image", "")))[0].rsplit("/", 1)[-1] in engines
        ]
        wanted = [(raw, parsed) for raw, parsed in wanted if parsed]
        if not wanted:
            report.add(
                OK,
                "data",
                path,
                f"{value}, {app} pins no comparable {engines[0]} version",
            )
            continue
        raw, parsed = max(wanted, key=lambda item: item[1])
        order = compare(found, parsed)
        if order > 0:
            report.add(
                FAIL, "data", path, f"{value} is newer than {app}'s {raw}: a downgrade"
            )
        elif order < 0 and kind == "PG_VERSION" and app == "svc-db-postgres":
            report.add(
                WARN,
                "data",
                path,
                f"{value} -> {raw}: the deploy runs pg_upgrade --link",
            )
        elif order < 0:
            steps = parsed[0] - found[0]
            report.add(
                WARN, "data", path, f"{value} -> {raw} of {app}, {steps} major step(s)"
            )
        else:
            report.add(OK, "data", path, f"{value}, {app} pins {raw}")


def images(report, applications, deployed, records):
    wanted: dict[tuple[str, str], set[str]] = defaultdict(set)
    for app in deployed:
        for _, service in pinned(app, applications[app]):
            key = (app, repo(str(service["image"]))[0])
            wanted[key].add(str(service["version"]))
    for fields in records["container"]:
        if len(fields) < 3:
            continue
        name, image = fields[0].lstrip("/"), fields[1]
        image_repo, tag = repo(image)
        app = owner(name, applications, deployed)
        if app:
            versions = wanted.get((app, image_repo), set())
        else:
            versions = set().union(
                *(v for (_, r), v in wanted.items() if r == image_repo)
            )
        if not versions:
            continue
        parsed = [p for p in (version(v) for v in versions) if p]
        running = version(tag)
        if tag in versions:
            report.add(OK, "images", name, image)
        elif not parsed or running is None:
            report.add(
                OK, "images", name, f"{image}, code pins {', '.join(sorted(versions))}"
            )
        else:
            newest = max(parsed)
            target = ".".join(map(str, newest))
            order = compare(running, newest)
            if order > 0:
                report.add(
                    FAIL,
                    "images",
                    name,
                    f"{image} is newer than the code's {target}: a downgrade",
                )
            elif order < 0:
                skipped = newest[0] - running[0] - 1
                note = f", skips {skipped} major(s)" if skipped > 0 else ""
                report.add(WARN, "images", name, f"{tag} -> {target}{note}")
            else:
                report.add(OK, "images", name, f"{image}, code pins {target}")
