"""Filter ``update_check``: judge a host's collected state against the current code.

Args:
    state: stdout of ``playbooks/update/files/state.sh``, one tab-separated
        record per line with its kind first.
    applications: ``lookup('applications')`` of the host.
    group_names: the host's inventory groups.
    deployed: ``lookup('application_closure', group_names)``, the roles a
        deploy of the host runs.
    compose_volumes: ``{application_id: lookup('compose_volumes')}``, ``None``
        where the lookup failed.
    redirects: the source domains of ``lookup('current_play_redirect_domains')``.
    server_dirs: ``lookup('nginx', 'directories.configuration.http_includes')``,
        the directories the current nginx configuration loads.
    secret_schemas: ``{application_id: parsed meta/secrets.yml}`` of the
        deployed applications that have one.
    inventory_rc: exit code of ``cli.administration.inventory.validate``.
    inventory_output: its output lines.

Returns:
    ``{"summary": [...], "detail": [...], "failures": int}``: the summary holds
    the counts and every warning and failure, the detail every row by area.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from utils.roles.entity.name import get_entity_name
from utils.update_check import network, storage
from utils.update_check.common import AREAS, FAIL, OK, WARN, Report

BACKUP_WARN_HOURS = 36
BACKUP_FAIL_HOURS = 24 * 7
DISK_WARN_PERCENT = 85
DISK_FAIL_PERCENT = 95


def _records(state: str) -> dict[str, list[list[str]]]:
    records: dict[str, list[list[str]]] = defaultdict(list)
    for line in state.splitlines():
        kind, _, rest = line.partition("\t")
        records[kind].append(rest.split("\t"))
    return records


def _credential_keys(node, prefix: str = ""):
    for key, value in (node or {}).items():
        if isinstance(value, dict) and not {"description", "algorithm"} & set(value):
            yield from _credential_keys(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}"


def _dig(node, dotted: str):
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _inventory(report, applications, group_names, deployed, schemas, rc, output):
    if rc:
        tail = "; ".join(line.strip() for line in output if line.strip())[-400:]
        report.add(FAIL, "inventory", "schema", f"validator exited {rc}: {tail}")
    else:
        report.add(OK, "inventory", "schema", "every key matches the role defaults")
    for group in sorted(group_names):
        if group not in applications:
            report.add(
                WARN,
                "inventory",
                group,
                "no application role of this name in the current code",
            )
    for app in deployed:
        primary = (applications[app].get("services") or {}).get(get_entity_name(app))
        lifecycle = (primary or {}).get("lifecycle")
        if isinstance(lifecycle, dict):
            lifecycle = lifecycle.get("stage")
        if lifecycle == "eol":
            report.add(FAIL, "inventory", app, "role is end of life")
        elif lifecycle == "deprecated":
            report.add(WARN, "inventory", app, "role is deprecated")
        if app not in schemas:
            continue
        credentials = (applications[app].get("secrets") or {}).get("credentials") or {}
        keys = list(_credential_keys((schemas[app] or {}).get("credentials")))
        missing = [key for key in keys if _dig(credentials, key) is None]
        if missing:
            report.add(
                WARN,
                "inventory",
                app,
                f"no credential {', '.join(missing)}: run inventory provision",
            )
        else:
            report.add(OK, "inventory", app, f"{len(keys)} credentials set")


def _operations(report, records, now):
    for fields in records["failedunit"]:
        report.add(WARN, "operations", fields[0], "unit failed")
    for fields in records["backup"]:
        repo = fields[0]
        if len(fields) < 3 or not fields[1]:
            report.add(WARN, "operations", repo, "backup repository is empty")
            continue
        hours = (now - int(float(fields[1]))) // 3600
        if hours > BACKUP_FAIL_HOURS:
            level = FAIL
        elif hours > BACKUP_WARN_HOURS:
            level = WARN
        else:
            level = OK
        report.add(
            level, "operations", repo, f"newest backup {fields[2]}, {hours} hours old"
        )
    for fields in records["disk"]:
        percent = (
            int(fields[1].rstrip("%"))
            if len(fields) > 1 and fields[1].rstrip("%").isdigit()
            else 0
        )
        if percent >= DISK_FAIL_PERCENT:
            level = FAIL
        elif percent >= DISK_WARN_PERCENT:
            level = WARN
        else:
            level = OK
        report.add(level, "operations", fields[0], f"{percent}% used")


def update_check(
    state,
    applications,
    group_names,
    deployed,
    compose_volumes,
    redirects,
    server_dirs,
    secret_schemas,
    inventory_rc,
    inventory_output,
):
    records = _records(state)
    now = int(records["now"][0][0])
    apps = sorted(app for app in deployed if app in applications)
    report = Report()
    _inventory(
        report,
        applications,
        group_names,
        apps,
        secret_schemas,
        int(inventory_rc),
        inventory_output,
    )
    expected_volumes = storage.expected_volumes(
        report, applications, compose_volumes, apps
    )
    storage.volumes(report, applications, group_names, records, expected_volumes)
    storage.data(report, applications, records, expected_volumes)
    storage.images(report, applications, apps, records)
    network.ports(report, applications, apps, records)
    network.networks(report, applications, apps, records)
    network.webserver(report, applications, apps, redirects, server_dirs, records, now)
    _operations(report, records, now)

    counts = Counter(level for level, *_ in report.rows)
    rank = {FAIL: 0, WARN: 1}
    summary = [f"{FAIL} {counts[FAIL]}   {WARN} {counts[WARN]}   {OK} {counts[OK]}"]
    summary += [
        f"{level} {area:<12} {subject}: {text}"
        for level, area, subject, text in sorted(
            (row for row in report.rows if row[0] != OK),
            key=lambda row: (rank[row[0]], AREAS.index(row[1])),
        )
    ]
    detail = [summary[0]]
    for area in AREAS:
        rows = [row for row in report.rows if row[1] == area]
        if rows:
            detail.append(f"\n===== {area} =====")
            detail += [f"{level} {subject}: {text}" for level, _, subject, text in rows]
    return {"summary": summary, "detail": detail, "failures": counts[FAIL]}


class FilterModule:
    def filters(self):
        return {"update_check": update_check}
