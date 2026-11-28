from __future__ import annotations

import sys

from monitoring.rules import (
    RULESETS,
    desired_rules,
    host_attributes,
    rule_conditions,
    rule_description,
    rule_prefix,
    rule_value,
)
from monitoring.survey import SCRIPT, RefusalError, RunError, checkmk_host_name

ROOT_FOLDER = "workspaces"
DISCOVERY_MODE = "fix_all"
POLLS = 60
POLL_SECONDS = 2
HTTP_OK = (200, 201, 204)
NO_CHANGES = 422
STILL_RUNNING = 302
DISCOVERY_STARTED = (200, 303)
DISCOVERY_FINISHED = "finished"


def folder_path(workspace):
    return f"/{ROOT_FOLDER}/{workspace}"


def folder_id(workspace):
    return f"~{ROOT_FOLDER}~{workspace}"


def named(changes):
    """Args:
    changes: pending Checkmk changes.

    Returns:
        Each change as ``<user>: <text>``, joined by ``; ``.
    """
    return "; ".join(
        f"{change.get('user_id')}: {change.get('text') or change.get('action_name') or change.get('id')}"
        for change in changes
    )


def _expect(status, body, allowed, what):
    if status not in allowed:
        raise RunError(f"{what} answered {status}: {body}")


class Checkmk:
    """Args:
    api: ``(method, path, payload=None, headers=None) -> (status, body)``.
    site: the site id the activation targets.
    sleep: waits the given seconds between two polls.
    user: the automation user the run signs in as.
    """

    def __init__(self, api, site, sleep, user):
        self.api = api
        self.site = site
        self.sleep = sleep
        self.user = user
        self.changed = False

    def refuse_pending_changes(self, own=False):
        """Args:
        own: whether the pending changes of the automation user are this
            run's own, as in the undo of an apply whose preflight found
            none, which its removal then activates.

        Returns:
            Whether Checkmk holds pending changes of the automation user.

        Raises:
            RefusalError: before any write, naming each pending change, when
                one is another user's, which the activation would refuse, or,
                unless ``own``, the automation user's of an earlier run,
                which may belong to another host and which no run activates
                unseen.
        """
        status, body = self.api(
            "GET", "/domain-types/activation_run/collections/pending_changes"
        )
        _expect(status, body, (200,), "reading the pending changes")
        changes = (body or {}).get("value") or []
        foreign = [c for c in changes if c.get("user_id") != self.user]
        if foreign:
            raise RefusalError(
                f"checkmk has pending changes of another user: {named(foreign)}"
            )
        if changes and not own:
            raise RefusalError(
                f"checkmk has pending changes of an earlier run: {named(changes)}:"
                " activate or revert them in Checkmk first"
            )
        return bool(changes)

    # HTTP_OK holds every status the REST API answers a successful write with.
    def _write(self, method, path, payload, what, allowed=HTTP_OK):
        headers = {"If-Match": "*"} if method in ("PUT", "DELETE") else None
        status, body = self.api(method, path, payload, headers)
        _expect(status, body, allowed, what)
        self.changed = True
        return body

    def folder_exists(self, workspace):
        status, body = self.api("GET", f"/objects/folder_config/{folder_id(workspace)}")
        if status == 404:
            return False
        _expect(status, body, (200,), f"reading folder {folder_path(workspace)}")
        return True

    def ensure_folder(self, workspace):
        if self.folder_exists(workspace):
            return
        self._write(
            "POST",
            "/domain-types/folder_config/collections/all",
            {"name": workspace, "title": workspace, "parent": f"/{ROOT_FOLDER}"},
            f"creating folder {folder_path(workspace)}",
        )

    def hosts(self, workspace):
        """Returns:
        ``{host name: attributes}`` of every host in the workspace's folder.
        """
        status, body = self.api(
            "GET", f"/objects/folder_config/{folder_id(workspace)}/collections/hosts"
        )
        if status == 404:
            return {}
        _expect(status, body, (200,), f"listing the hosts of {folder_path(workspace)}")
        return {
            str(host.get("id")): (host.get("extensions") or {}).get("attributes") or {}
            for host in (body or {}).get("value") or []
        }

    def rules(self, prefix, ruleset):
        """Returns:
        Every rule of ``ruleset`` whose description starts with ``prefix``.
        """
        status, body = self.api(
            "GET", f"/domain-types/rule/collections/all?ruleset_name={ruleset}"
        )
        _expect(status, body, (200,), f"listing {ruleset}")
        return [
            rule
            for rule in (body or {}).get("value") or []
            if rule_description(rule).startswith(prefix)
        ]

    def converge_host(self, workspace, name, desired, held):
        if name not in held:
            self._write(
                "POST",
                "/domain-types/host_config/collections/all",
                {
                    "folder": folder_path(workspace),
                    "host_name": name,
                    "attributes": desired,
                },
                f"creating host {name}",
            )
            return
        if {key: held[name].get(key) for key in desired} == desired:
            return
        self._write(
            "PUT",
            f"/objects/host_config/{name}",
            {"attributes": desired},
            f"updating host {name}",
        )

    def converge_rules(self, workspace, host, name, desired):
        """Args:
        workspace: ``ws-<id>``.
        host: the inventory host whose rules alone are touched.
        name: its Checkmk host name.
        desired: ``{description: (ruleset, value)}``.
        """
        for ruleset in RULESETS:
            wanted = {d: v for d, (r, v) in desired.items() if r == ruleset}
            for rule in self.rules(rule_prefix(workspace, host), ruleset):
                description = rule_description(rule)
                if description not in wanted:
                    self._write(
                        "DELETE",
                        f"/objects/rule/{rule['id']}",
                        None,
                        f"deleting rule {description}",
                    )
                    continue
                value = wanted.pop(description)
                conditions = (rule.get("extensions") or {}).get("conditions") or {}
                if (
                    rule_value(rule) == value
                    and conditions.get("host_name")
                    == rule_conditions(name)["host_name"]
                ):
                    continue
                self._write(
                    "PUT",
                    f"/objects/rule/{rule['id']}",
                    {
                        "properties": {"description": description, "disabled": False},
                        "value_raw": repr(value),
                        "conditions": rule_conditions(name),
                    },
                    f"updating rule {description}",
                )
            for description, value in sorted(wanted.items()):
                self._write(
                    "POST",
                    "/domain-types/rule/collections/all",
                    {
                        "ruleset": ruleset,
                        "folder": folder_path(workspace),
                        "properties": {"description": description, "disabled": False},
                        "value_raw": repr(value),
                        "conditions": rule_conditions(name),
                    },
                    f"creating rule {description}",
                )

    def discover(self, name, required=False):
        """Args:
        name: the Checkmk host.
        required: whether a discovery Checkmk does not start, or whose job
            ends in any state but ``finished``, fails the run.
        """
        status, _ = self.api(
            "POST",
            "/domain-types/service_discovery_run/actions/start/invoke",
            {"host_name": name, "mode": DISCOVERY_MODE},
        )
        if status not in DISCOVERY_STARTED and required:
            raise RunError(
                f"discovering {name} answered {status}: the services its agent gave stay"
            )
        if status not in DISCOVERY_STARTED:
            print(f"{SCRIPT}: discovering {name} answered {status}", file=sys.stderr)
            return
        for _ in range(POLLS):
            status, body = self.api(
                "GET",
                f"/objects/service_discovery_run/{name}/actions/wait-for-completion/invoke",
            )
            if status != STILL_RUNNING:
                _expect(
                    status, body, (200, 204), f"waiting for the discovery of {name}"
                )
                status, body = self.api("GET", f"/objects/service_discovery_run/{name}")
                _expect(status, body, (200,), f"reading the discovery of {name}")
                state = ((body or {}).get("extensions") or {}).get("state")
                if state == DISCOVERY_FINISHED:
                    return
                if required:
                    raise RunError(f"the discovery of {name} ended {state}")
                print(
                    f"{SCRIPT}: the discovery of {name} ended {state}", file=sys.stderr
                )
                return
            self.sleep(POLL_SECONDS)
        raise RunError(f"the discovery of {name} still runs")

    def activate(self):
        status, body = self.api(
            "POST",
            "/domain-types/activation_run/actions/activate-changes/invoke",
            {"redirect": False, "sites": [self.site], "force_foreign_changes": False},
            {"If-Match": "*"},
        )
        if status == NO_CHANGES:
            return
        _expect(status, body, (200, 201, STILL_RUNNING), "activating changes")
        activation = (body or {}).get("id")
        if not activation:
            return
        for _ in range(POLLS):
            status, body = self.api(
                "GET",
                f"/objects/activation_run/{activation}/actions/wait-for-completion/invoke",
            )
            if status != STILL_RUNNING:
                _expect(status, body, (200, 204), "waiting for the activation")
                return
            self.sleep(POLL_SECONDS)
        raise RunError(f"the activation {activation} still runs")

    def apply(self, planned, tls_days):
        """Args:
        planned: the result of ``plan`` for ``apply``.
        tls_days: ``(warn, crit)`` days of the TLS expiry check.

        Returns:
            Whether MONITOR_HOST is in Checkmk; no other host is touched. A
            held host without the agent share is discovered again, so the
            services an earlier agent gave go with it, also after a run
            that died between the tag change and the discovery.
        """
        workspace, host, entry = planned["alias"], planned["host"], planned["entry"]
        if not entry["checkmk"]:
            return self.remove(workspace, host)
        self.refuse_pending_changes()
        name = checkmk_host_name(workspace, host)
        self.ensure_folder(workspace)
        held = self.hosts(workspace)
        self.converge_rules(
            workspace, host, name, desired_rules(workspace, host, entry, tls_days)
        )
        self.converge_host(
            workspace, name, host_attributes(workspace, host, entry), held
        )
        if self.changed:
            self.activate()
        if entry["share"]["agent"] or name in held:
            self.discover(name, required=not entry["share"]["agent"])
            self.activate()
        return True

    def remove(self, workspace, host, own=False):
        """Args:
        workspace: ``ws-<id>``.
        host: MONITOR_HOST.
        own: whether the automation user's pending changes are this run's,
            as in the undo of an apply (``MONITOR_UNDO``); they are then
            activated with the removal, also when the folder is gone.

        Returns:
            False: MONITOR_HOST's Checkmk host and rules are gone, and the
            workspace's folder when this run removed its last host; a host
            Checkmk does not hold changes nothing.
        """
        held_changes = self.refuse_pending_changes(own)
        if not self.folder_exists(workspace):
            if held_changes:
                self.activate()
            return False
        name = checkmk_host_name(workspace, host)
        held = self.hosts(workspace)
        self.converge_rules(workspace, host, name, {})
        if name in held:
            self._write(
                "DELETE", f"/objects/host_config/{name}", None, f"deleting host {name}"
            )
        if name in held and not set(held) - {name}:
            self._write(
                "DELETE",
                f"/objects/folder_config/{folder_id(workspace)}",
                None,
                f"deleting folder {folder_path(workspace)}",
            )
        if self.changed or held_changes:
            self.activate()
        return False
