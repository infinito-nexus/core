from __future__ import annotations

import ipaddress
import re
from collections import defaultdict

from utils.roles.entity.name import get_entity_name
from utils.update_check.common import FAIL, OK, WARN, owner, services

CERT_WARN_DAYS = 21
CERT_FAIL_DAYS = 7
_PROCESS = re.compile(r'users:\(\("([^"]+)"')


def _port_numbers(value) -> list[int]:
    text = str(value).strip()
    if text.isdigit():
        return [int(text)]
    low, dash, high = text.partition("-")
    if dash and low.isdigit() and high.isdigit():
        return list(range(int(low), int(high) + 1))
    return []


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _strings(value)


def _covered(domain: str, names: set[str]) -> bool:
    parent = domain.split(".", 1)[-1]
    return domain in names or f"*.{parent}" in names


def ports(report, applications, deployed, records):
    declared: dict[int, list[tuple[str, bool]]] = defaultdict(list)
    for app in deployed:
        for _, service in services(app, applications[app]):
            declared_ports = service.get("ports") or {}
            local = declared_ports.get("local") or {}
            public = declared_ports.get("public") or {}
            for proto in set(local) | set(public):
                value = local[proto] if proto in local else public[proto]
                for port in _port_numbers(value):
                    declared[port].append((app, proto in local))
    holders: dict[int, set[str]] = defaultdict(set)
    bound: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for fields in records["binding"]:
        if len(fields) < 4 or not fields[2].isdigit():
            continue
        container = fields[0].lstrip("/")
        holders[int(fields[2])].add(container)
        bound[(fields[1], fields[2], fields[3].rsplit("/", 1)[-1])].append(container)
    processes: dict[int, set[str]] = defaultdict(set)
    for fields in records["listen"]:
        columns = fields[0].split()
        if len(columns) < 5:
            continue
        port = columns[4].rsplit(":", 1)[-1]
        if not port.isdigit():
            continue
        if len(fields) > 1 and fields[1]:
            holders[int(port)].add(fields[1])
            continue
        process = _PROCESS.search(fields[0])
        name = process.group(1) if process else "?"
        if name not in ("docker-proxy", "dockerd"):
            processes[int(port)].add(name)
    for (ip, port, transport), containers in sorted(bound.items()):
        if len(set(containers)) > 1:
            report.add(
                WARN,
                "ports",
                f"{ip or '*'}:{port}/{transport}",
                f"bound by {', '.join(sorted(set(containers)))}: only one of them can run",
            )
    for port, owners in sorted(declared.items()):
        owning = {app for app, _ in owners}
        apps = ", ".join(sorted(owning))
        local_apps = sorted({app for app, local in owners if local})
        if len(local_apps) > 1:
            report.add(
                FAIL, "ports", str(port), f"declared local by {', '.join(local_apps)}"
            )
            continue
        if processes.get(port):
            report.add(
                FAIL,
                "ports",
                str(port),
                f"{apps} needs it, host process {', '.join(sorted(processes[port]))} listens on it",
            )
            continue
        foreign = sorted(
            holder
            for holder in holders.get(port, set())
            if owner(holder, applications, deployed) not in owning
        )
        if foreign:
            report.add(
                WARN,
                "ports",
                str(port),
                f"{apps} needs it, container {', '.join(foreign)} binds it",
            )
        else:
            report.add(OK, "ports", str(port), apps)


def networks(report, applications, deployed, records):
    subnets = []
    for app in deployed:
        subnet = ((applications[app].get("networks") or {}).get("local") or {}).get(
            "subnet"
        )
        try:
            subnets.append((app, ipaddress.ip_network(str(subnet), strict=False)))
        except ValueError:
            continue
    for index, (app, subnet) in enumerate(subnets):
        for other, other_subnet in subnets[index + 1 :]:
            if subnet.overlaps(other_subnet):
                report.add(
                    FAIL,
                    "networks",
                    str(subnet),
                    f"{app} overlaps {other} ({other_subnet})",
                )
    actual = []
    for fields in records["network"]:
        for value in fields[1:]:
            try:
                actual.append((fields[0], ipaddress.ip_network(value, strict=False)))
            except ValueError:
                continue
    for app, subnet in subnets:
        entity = get_entity_name(app)
        clashes = sorted(
            name
            for name, network in actual
            if network.version == subnet.version
            and network.overlaps(subnet)
            and not (entity and entity in name)
        )
        if clashes:
            report.add(
                WARN,
                "networks",
                str(subnet),
                f"{app} needs it, docker network {', '.join(clashes)} overlaps it",
            )
        else:
            report.add(OK, "networks", str(subnet), app)


def webserver(report, applications, deployed, redirects, server_dirs, records, now):
    tests = records["webtest"]
    for fields in tests:
        if len(fields) < 3:
            continue
        level = OK if fields[1] == "0" else FAIL
        report.add(level, "webserver", fields[0], fields[2])
    if not tests:
        report.add(
            WARN,
            "webserver",
            "openresty",
            "no running OpenResty container, the configuration is untested",
        )
    expected = {}
    for app in deployed:
        for domain in _strings(applications[app].get("domains")):
            if "." in domain and "{{" not in domain:
                expected.setdefault(domain, app)
    for domain in redirects:
        expected.setdefault(str(domain), "redirect")
    served: dict[str, str] = {}
    legacy: dict[str, str] = {}
    for fields in records["servername"]:
        if len(fields) < 2:
            continue
        loaded = any(fields[0].startswith(str(d)) for d in server_dirs)
        for name in fields[1].split():
            if name != "_" and not name.startswith("~"):
                (served if loaded else legacy).setdefault(name, fields[0])
    for domain, app in sorted(expected.items()):
        if domain in served:
            report.add(OK, "webserver", domain, f"{app}, {served[domain]}")
        else:
            report.add(
                WARN,
                "webserver",
                domain,
                f"{app} has no server block yet, the deploy writes it",
            )
    for name, path in sorted(served.items()):
        if name not in expected:
            report.add(
                WARN,
                "webserver",
                name,
                f"{path} is loaded, no deployed role wants it: delete it",
            )
    for name, path in sorted(legacy.items()):
        if name not in expected and name not in served:
            report.add(
                WARN,
                "webserver",
                name,
                f"served by the old layout ({path}), the current code drops it: "
                "add it to domains.aliases or let it go",
            )
    if legacy:
        report.add(
            WARN,
            "webserver",
            "old layout",
            f"{len(set(legacy.values()))} server block files the current "
            "configuration does not load: delete them in the cleanup",
        )
    sans: set[str] = set()
    for fields in records["cert"]:
        if len(fields) < 3 or not fields[1].isdigit():
            continue
        sans.update(filter(None, fields[2].split(",")))
        days = (int(fields[1]) - now) // 86400
        if days < CERT_FAIL_DAYS:
            level = FAIL
        elif days < CERT_WARN_DAYS:
            level = WARN
        else:
            level = OK
        report.add(level, "certificates", fields[0], f"expires in {days} days")
    for domain, app in sorted(expected.items()):
        if not _covered(domain, sans):
            report.add(
                WARN, "certificates", domain, f"{app}: no certificate covers it yet"
            )
