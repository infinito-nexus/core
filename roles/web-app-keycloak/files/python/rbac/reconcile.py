#!/usr/bin/env python3
"""Reconcile Keycloak's per-application RBAC groups and LDAP group mappers over the admin REST API.

Env:
    KC_URL: Keycloak base URL reachable from the network namespace the script runs in.
    KC_PID: host PID of the Keycloak container, whose environment holds the admin credentials.
    KC_REALM: realm holding the RBAC groups.
    LDAP_COMPONENT_ID: LDAP user storage component id, parent of the group mappers.
    RBAC_ROOT_PATH: path of the RBAC root group, e.g. ``/roles``.
    DEPLOYED_APP_IDS: space-separated application ids whose groups stay under the root.
    PAYLOADS_FILE: one ``<app_id> <mapper_name> <base64 mapper JSON> <fingerprint>`` line per app.
    WORKERS: apps reconciled in parallel.
    SYNC_ATTEMPTS: mapper sync attempts per app.
    SYNC_DELAY: seconds between two sync attempts.
    SYNC_TIMEOUT: seconds one sync attempt may take.

Output: one ``<step>-failed <app_id>`` line per failed app, then one ``summary`` line.
Exit: 0 every app reconciled, 2 only mapper syncs failed, 1 otherwise.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from keycloak_admin import Keycloak, KeycloakError, container_credentials

SHARED_MAPPER = "ldap-roles"
MAPPER_TYPE = "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
FINGERPRINT = "infinito.rbac.fingerprint"


class StepError(Exception):
    def __init__(self, step: str, cause: Exception) -> None:
        super().__init__(f"{step}: {cause}")
        self.step = step


@dataclass
class App:
    app_id: str
    mapper_name: str
    payload: str
    fingerprint: str


def read_payloads(path: str) -> list[App]:
    """Return the apps of a payloads file.

    Args:
        path: file with one ``<app_id> <mapper_name> <base64 JSON> <fingerprint>`` line per app.
    """
    with Path(path).open(encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    apps = []
    for line in lines:
        if line.strip():
            app_id, mapper_name, encoded, fingerprint = line.split()
            apps.append(
                App(
                    app_id, mapper_name, base64.b64decode(encoded).decode(), fingerprint
                )
            )
    return apps


def ldap_mappers(kc: Keycloak, ldap_id: str) -> dict[str, dict]:
    """Return the LDAP group mappers by name.

    Args:
        kc: client.
        ldap_id: LDAP user storage component id.
    """
    query = urllib.parse.urlencode({"parent": ldap_id, "type": MAPPER_TYPE})
    found, _ = kc.call("GET", f"components?{query}")
    return {mapper["name"]: mapper for mapper in found}


def drop_shared_mapper(kc: Keycloak, mappers: dict[str, dict]) -> list[str]:
    """Delete the shared mapper whose flat groups would shadow the per-app ones.

    Args:
        kc: client.
        mappers: LDAP group mappers by name.

    Returns:
        One ``drop-failed`` line per mapper that could not be deleted.
    """
    shared = mappers.pop(SHARED_MAPPER, None)
    if shared is None:
        return []
    try:
        kc.call("DELETE", f"components/{shared['id']}")
    except (KeycloakError, OSError) as error:
        return [f"drop-failed {SHARED_MAPPER}: {error}"]
    return []


def purge_orphans(
    kc: Keycloak, root_id: str, keep: set[str], workers: int
) -> tuple[dict[str, str], list[str]]:
    """Delete root subgroups that belong to no deployed app.

    Args:
        kc: client.
        root_id: RBAC root group id.
        keep: application ids whose groups stay.
        workers: parallel deletes.

    Returns:
        The kept subgroup ids by name, and one ``purge-failed`` line per failed delete.
    """
    kept, orphans = {}, []
    for group in kc.children(root_id):
        if group["name"] in keep:
            kept[group["name"]] = group["id"]
        else:
            orphans.append(group)

    def delete(group: dict) -> str:
        try:
            kc.call("DELETE", f"groups/{group['id']}")
        except (KeycloakError, OSError) as error:
            return f"purge-failed {group['name']}: {error}"
        return ""

    with ThreadPoolExecutor(max_workers=workers) as pool:
        failures = [line for line in pool.map(delete, orphans) if line]
    return kept, failures


def config_matches(current: dict, desired: dict) -> bool:
    """True when every config key the payload sets already has its value.

    Args:
        current: mapper as Keycloak returns it.
        desired: mapper payload.
    """
    have = current.get("config") or {}
    return all(have.get(key) == value for key, value in desired["config"].items())


class Reconciler:
    """Bring one app's group, mapper and LDAP group import up to date.

    Args:
        kc: client.
        ldap_id: LDAP user storage component id.
        root_id: RBAC root group id.
        groups: existing app group ids by name.
        mappers: existing LDAP group mappers by name.
        sync_attempts: mapper sync attempts.
        sync_delay: seconds between two attempts.
        sync_timeout: seconds one attempt may take.
    """

    def __init__(
        self,
        kc: Keycloak,
        ldap_id: str,
        root_id: str,
        groups: dict[str, str],
        mappers: dict[str, dict],
        sync_attempts: int,
        sync_delay: float,
        sync_timeout: int,
    ) -> None:
        self.kc = kc
        self.ldap_id = ldap_id
        self.root_id = root_id
        self.groups = groups
        self.mappers = mappers
        self.sync_attempts = sync_attempts
        self.sync_delay = sync_delay
        self.sync_timeout = sync_timeout

    def _step(self, step: str, action, *args):
        try:
            return action(*args)
        except (KeycloakError, OSError, ValueError, KeyError) as error:
            raise StepError(step, error) from None

    def _ensure_group(self, app: App) -> tuple[str, bool]:
        group_id = self.groups.get(app.app_id)
        if group_id:
            return group_id, False
        _, group_id = self.kc.call(
            "POST", f"groups/{self.root_id}/children", {"name": app.app_id}
        )
        if not group_id:
            raise KeycloakError("created group carries no id")
        return group_id, True

    def _upsert_mapper(self, app: App) -> tuple[str, bool]:
        desired = json.loads(app.payload)
        current = self.mappers.get(app.mapper_name)
        if current is None:
            _, mapper_id = self.kc.call("POST", "components", desired)
            if not mapper_id:
                raise KeycloakError("created mapper carries no id")
            return mapper_id, True
        if config_matches(current, desired):
            return current["id"], False
        self.kc.call(
            "PUT", f"components/{current['id']}", {**desired, "id": current["id"]}
        )
        return current["id"], True

    def _sync(self, mapper_id: str) -> None:
        path = f"user-storage/{self.ldap_id}/mappers/{mapper_id}/sync?direction=fedToKeycloak"
        for attempt in range(1, self.sync_attempts + 1):
            try:
                self.kc.call("POST", path, timeout=self.sync_timeout)
            except (KeycloakError, OSError):
                if attempt == self.sync_attempts:
                    raise
                time.sleep(self.sync_delay)
            else:
                return

    def _record(self, group_id: str, group: dict, fingerprint: str) -> None:
        attributes = {**(group.get("attributes") or {}), FINGERPRINT: [fingerprint]}
        self.kc.call("PUT", f"groups/{group_id}", {**group, "attributes": attributes})

    def run(self, app: App) -> str:
        """Return ``synced`` or ``unchanged`` for an app.

        Args:
            app: the app to reconcile.
        """
        group_id, created = self._step("ensure", self._ensure_group, app)
        mapper_id, changed = self._step("upsert", self._upsert_mapper, app)
        group, _ = self._step("read", self.kc.call, "GET", f"groups/{group_id}")
        stored = ((group.get("attributes") or {}).get(FINGERPRINT) or [""])[0]
        if not (created or changed or stored != app.fingerprint):
            return "unchanged"
        self._step("sync", self._sync, mapper_id)
        self._step("record", self._record, group_id, group, app.fingerprint)
        return "synced"


def main() -> int:
    env = os.environ
    workers = int(env["WORKERS"])
    try:
        kc = Keycloak(
            env["KC_URL"],
            env["KC_REALM"],
            *container_credentials(Path("/proc") / env["KC_PID"] / "environ"),
        )
        mappers = ldap_mappers(kc, env["LDAP_COMPONENT_ID"])
        warnings = drop_shared_mapper(kc, mappers)
        root, _ = kc.call(
            "GET",
            f"group-by-path/{urllib.parse.quote(env['RBAC_ROOT_PATH'].strip('/'))}",
        )
        groups, purge_failures = purge_orphans(
            kc, root["id"], set(env["DEPLOYED_APP_IDS"].split()), workers
        )
    except (KeycloakError, OSError, KeyError, ValueError) as error:
        print(f"listing-failed {error}")
        return 1
    for line in warnings + purge_failures:
        print(line, file=sys.stderr)

    reconciler = Reconciler(
        kc,
        env["LDAP_COMPONENT_ID"],
        root["id"],
        groups,
        mappers,
        int(env["SYNC_ATTEMPTS"]),
        float(env["SYNC_DELAY"]),
        int(env["SYNC_TIMEOUT"]),
    )

    def run(app: App) -> tuple[App, str]:
        try:
            return app, reconciler.run(app)
        except StepError as error:
            print(f"{app.app_id}: {error}", file=sys.stderr)
            return app, f"{error.step}-failed"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, read_payloads(env["PAYLOADS_FILE"])))

    failed = [(app, outcome) for app, outcome in results if outcome.endswith("-failed")]
    for app, outcome in failed:
        print(f"{outcome} {app.app_id}")
    counts = {
        key: sum(1 for _, o in results if o == key) for key in ("synced", "unchanged")
    }
    print(
        f"summary synced={counts['synced']} unchanged={counts['unchanged']} "
        f"failed={len(failed)} purged-failures={len(purge_failures)}"
    )
    if any(outcome != "sync-failed" for _, outcome in failed):
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
