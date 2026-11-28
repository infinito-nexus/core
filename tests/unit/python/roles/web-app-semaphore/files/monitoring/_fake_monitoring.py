from __future__ import annotations

import importlib
import ipaddress
from importlib.util import module_from_spec, spec_from_file_location
from urllib.parse import unquote

from utils import PROJECT_ROOT

FILES = PROJECT_ROOT / "roles" / "web-app-semaphore" / "files"
SCRIPT = FILES / "python" / "monitoring.py"
SHELL = FILES / "shell" / "repository" / "monitoring.sh"
MODULES = ("survey", "plan", "rules", "checkmk", "rest", "prometheus", "openbao")
PARENT = "." * 2
ID = "0a1b2c3d-0000-4000-8000-00000000000a"
WS = f"ws-{ID}"
SITE = "cmk"
TLS_DAYS = (30, 14)
RULES = "/domain-types/rule/collections/all"
HOST_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
)
SETTINGS = {
    "MONITOR_CHECKMK_API": "https://checkmk.example.org/cmk/check_mk/api/1.0",
    "MONITOR_CHECKMK_SITE": SITE,
    "MONITOR_CACERT": "/etc/ssl/ca.pem",
    "MONITOR_TLS_WARN_DAYS": "30",
    "MONITOR_TLS_CRIT_DAYS": "14",
    "MONITOR_PROMETHEUS_DIR": "/etc/prometheus/instances",
    "MONITOR_PROMETHEUS_RELOAD_URL": "http://127.0.0.1:9090/-/reload",
    "WORKSPACE_PRIVATE_TARGETS": "[]",
}
SHELL_SETTINGS = {
    "SEMAPHORE_JWT": "jwt",
    "MONITOR_INVENTORY_REPOSITORY": "ssh://git@git.example.org/{workspace}.git",
    "MONITOR_INVENTORY_FILE": "devices.yml",
    "DEPLOY_VAULT_PASSWORD": "v",
    "DEPLOY_LOGIN": "deploy",
    "DEPLOY_KNOWN_HOSTS": "",
    "SSH_AUTH_SOCK": "/run/agent.sock",
    "WORKSPACE_INVENTORY_FILE": "devices.yml",
    "BAO_ADDR": "https://openbao.example.org",
    "BAO_CACERT": "/etc/ssl/ca.pem",
    "BAO_MONITORING_ROLE": "monitoring",
    "BAO_TOKEN_FILE": "/run/bao-token",
    "INFINITO_SRC_DIR": str(PROJECT_ROOT),
}
COMMIT = "0123456789abcdef0123456789abcdef01234567"
AUTOMATION = "automation"
PENDING = "/domain-types/activation_run/collections/pending_changes"


def _load_script():
    """Returns:
    The ``monitoring.py`` script, its ``monitoring`` package importable as
    the runner imports it.
    """
    spec = spec_from_file_location("monitoring_script", SCRIPT)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


monitoring = _load_script()
survey, planner, rules, cmk, rest, prometheus, openbao = (
    importlib.import_module(f"monitoring.{name}") for name in MODULES
)
RefusalError = survey.RefusalError
RunError = survey.RunError


def env(action="apply", host="target", **extra):
    survey_values = (
        {"INVENTORY_COMMIT": COMMIT, "DNS_LABEL": "target"}
        if action != "remove"
        else {}
    )
    return {
        "WORKSPACE": ID,
        "MONITOR_ACTION": action,
        "MONITOR_HOST": host,
        **survey_values,
        **SETTINGS,
        **SHELL_SETTINGS,
        **extra,
    }


def inventory(**hosts):
    return {"_meta": {"hostvars": hosts}}


def target(share=None, primary="target.example.org", **extra):
    variables = {
        "ansible_host": "192.0.2.10",
        "ansible_user": "deploy",
        "ssh_host_key": HOST_KEY,
        "DOMAIN_PRIMARY": primary,
        "applications": {
            "web-app-prometheus": {
                "server": {"domains": {"canonical": [f"prometheus.{primary}"]}}
            }
        },
        **extra,
    }
    if share is not None:
        variables["platform_monitoring"] = share
    return variables


DOCUMENTATION = tuple(
    ipaddress.ip_network(network)
    for network in ("192.0.2.0/24", "203.0.113.0/24", "2001:db8::/32")
)


def public(_name):
    return ["203.0.113.10", "2001:db8::10"]


def planned_for(
    host="target",
    action="apply",
    private=DOCUMENTATION,
    primary=None,
    resolver=public,
    **hosts,
):
    """Args:
    host: MONITOR_HOST.
    action: ``apply`` or ``remove``.
    private: the networks WORKSPACE_PRIVATE_TARGETS opens; the documentation
        ranges the fixtures use unless given, as they are not global.
    primary: the deploy domain ``deploy_domain`` builds; None stands for the
        one the planned host's inventory names, as a consistent store sends.
    resolver: the stand-in resolver, every name public unless given.
    hosts: the inventory hosts, ``target`` alone when none.

    Returns:
        The plan of ``monitoring.plan``.
    """
    hosts = hosts or {host: target()}
    if primary is None:
        primary = (hosts.get(host) or {}).get("DOMAIN_PRIMARY", "")
    return planner.plan(
        ID, action, host, inventory(**hosts), private, primary, resolver
    )


def removed_plan():
    """Returns:
    The plan of ``remove`` for ``target``, which plans no entry.
    """
    return planner.plan(ID, "remove", "target", {}, [], "", public)


class FakeCheckmk:
    """Args:
    status: overrides the answer of every call when set.
    """

    def __init__(self, status=None):
        self.status = status
        self.folders = {"~workspaces"}
        self.hosts = {}
        self.rules = {}
        self.discovered = set()
        self.discovery_state = "finished"
        self.pending = 0
        self.foreign = []
        self.activations = 0
        self.calls = []

    def _folder_of(self, path):
        return "~" + path.strip("/").replace("/", "~")

    def __call__(self, method, path, payload=None, headers=None):
        self.calls.append((method, path, payload, headers))
        if self.status is not None:
            return self.status, {"detail": "refused"}
        if method == "GET" and path == PENDING:
            users = [*self.foreign, *([AUTOMATION] * self.pending)]
            return 200, {
                "value": [
                    {"user_id": user, "text": f"edit by {user}"} for user in users
                ]
            }
        if path.startswith("/objects/folder_config/") and path.endswith(
            "/collections/hosts"
        ):
            folder = path.split("/")[3]
            if folder not in self.folders:
                return 404, {}
            return 200, {
                "value": [
                    {"id": name, "extensions": {"attributes": host["attributes"]}}
                    for name, host in self.hosts.items()
                    if host["folder"] == folder
                ]
            }
        if path.startswith("/objects/folder_config/"):
            folder = path.split("/")[3]
            if method == "GET":
                return (200, {}) if folder in self.folders else (404, {})
            self.folders.discard(folder)
            return self._changed(204)
        if path == "/domain-types/folder_config/collections/all":
            self.folders.add(self._folder_of(f"{payload['parent']}/{payload['name']}"))
            return self._changed(200)
        if path == "/domain-types/host_config/collections/all":
            self.hosts[payload["host_name"]] = {
                "folder": self._folder_of(payload["folder"]),
                "attributes": dict(payload["attributes"]),
            }
            return self._changed(200)
        if path.startswith("/objects/host_config/"):
            name = path.rsplit("/", 1)[1]
            if method == "PUT":
                self.hosts[name]["attributes"] = dict(payload["attributes"])
            else:
                del self.hosts[name]
                self.discovered.discard(name)
            return self._changed(200)
        if method == "GET" and path.startswith(RULES):
            ruleset = path.split("ruleset_name=")[1]
            return 200, {
                "value": [r for r in self.rules.values() if r["ruleset"] == ruleset]
            }
        if method == "POST" and path == RULES:
            rule_id = f"r{len(self.rules)}-{len(self.calls)}"
            self.rules[rule_id] = self._rule(rule_id, payload["ruleset"], payload)
            return self._changed(200)
        if path.startswith("/objects/rule/"):
            rule_id = path.rsplit("/", 1)[1]
            if method == "PUT":
                self.rules[rule_id] = self._rule(
                    rule_id, self.rules[rule_id]["ruleset"], payload
                )
            else:
                del self.rules[rule_id]
            return self._changed(200)
        if path.endswith("/activate-changes/invoke"):
            if not self.pending:
                return 422, {"title": "no changes"}
            self.pending = 0
            self.activations += 1
            return 200, {}
        if path.endswith("/service_discovery_run/actions/start/invoke"):
            name = payload["host_name"]
            agent = self.hosts[name]["attributes"].get("tag_agent") == "cmk-agent"
            if agent != (name in self.discovered):
                self.discovered.symmetric_difference_update({name})
                self.pending += 1
            return 200, {}
        if path.endswith("/actions/wait-for-completion/invoke"):
            return 204, {}
        if method == "GET" and path.startswith("/objects/service_discovery_run/"):
            return 200, {"extensions": {"state": self.discovery_state}}
        raise AssertionError(f"unexpected call {method} {path}")

    def _changed(self, status):
        self.pending += 1
        return status, {}

    @staticmethod
    def _rule(rule_id, ruleset, payload):
        return {
            "id": rule_id,
            "ruleset": ruleset,
            "extensions": {
                "properties": payload["properties"],
                "value_raw": payload["value_raw"],
                "conditions": payload["conditions"],
            },
        }

    def writes(self):
        return [
            (method, path)
            for method, path, _payload, _headers in self.calls
            if method in ("POST", "PUT", "DELETE")
            and "activate-changes" not in path
            and "service_discovery_run" not in path
        ]

    def discoveries(self):
        return [
            payload
            for method, path, payload, _headers in self.calls
            if method == "POST"
            and path.endswith("/service_discovery_run/actions/start/invoke")
        ]


def checkmk(site):
    return cmk.Checkmk(site, SITE, lambda _s: None, AUTOMATION)


def apply(site, host="target", **hosts):
    return checkmk(site).apply(planned_for(host, **hosts), TLS_DAYS)


def name_of(host):
    return survey.checkmk_host_name(WS, host)


class FakeBao:
    """Args:
    entries: the ``{"<mount>/<path>": fields}`` of KV v2 it starts with.
    failing: ``{"<mount>/<path>": status}`` answered to every request on
        that entry.
    """

    def __init__(self, entries, failing=None):
        self.entries = dict(entries)
        self.failing = failing or {}
        self.reads = []
        self.writes = []

    def read_all(self, mount, path):
        self.reads.append(f"{mount}/{path}")
        if f"{mount}/{path}" not in self.entries:
            raise LookupError(path)
        return dict(self.entries[f"{mount}/{path}"])

    def write_create_only(self, mount, path, data):
        if f"{mount}/{path}" in self.entries:
            return False
        self.write(mount, path, data)
        return True

    def write(self, mount, path, data):
        self.writes.append(f"{mount}/{path}")
        self.entries[f"{mount}/{path}"] = dict(data)

    def list_tree(self, mount, prefix):
        folder = f"{mount}/{prefix}"
        return sorted(
            path.removeprefix(folder)
            for path in self.entries
            if path.startswith(folder)
        )

    def request(self, method, path, _body):
        kind = "/metadata/" if "/metadata/" in path else "/data/"
        mount, _, rest_of_path = path.partition(kind)
        record = unquote(f"{mount}/{rest_of_path}")
        if record in self.failing:
            return self.failing[record], {}
        if method == "GET":
            self.reads.append(record)
            if record not in self.entries:
                return 404, {}
            return 200, {"data": {"data": dict(self.entries[record])}}
        self.writes.append(f"{method} {record}")
        self.entries.pop(record, None)
        return 204, {}


PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlatformMonitoringKey infinito-monitoring"
)
WORKSPACE_DIGEST_FILE = "/srv/workspace-core/nginx/conf.d/federate.sha256"
INVENTORY = f"platform/monitoring/inventory/{WS}"
LOGIN = {
    "platform/monitoring/checkmk": {"username": "monitoring", "secret": "s"},
    "platform/monitoring/agent-key": {"public_key": PUBLIC_KEY},
    INVENTORY: {
        "private_key": "k",
        "dns_zone": "ws.example.org",
        "digest_file": WORKSPACE_DIGEST_FILE,
    },
}
RELEASED = f"monitoring/{WS}/released/target"
MONITORED = f"platform/monitoring/inventory/{WS}/hosts/target"
TOKEN = f"platform/monitoring/federation/{WS}/target"
DIGEST = f"monitoring/{WS}/federation/target"
AGENT_KEY = f"monitoring/{WS}/agent/target"
RELEASING = f"monitoring/{WS}/releasing/target"
OTHER_TOKEN = f"platform/monitoring/federation/{WS}/other"
OTHER_DIGEST = f"monitoring/{WS}/federation/other"
LABEL = f"monitoring/{WS}/labels/target"


class Interleaved(FakeBao):
    """Args:
    entries: the entries it starts with.
    events: per operation index, the calls that run before it.
    """

    def __init__(self, entries, events):
        super().__init__(entries)
        self.events = events
        self.ops = 0

    def tick(self):
        for event in self.events.get(self.ops, []):
            event(self)
        self.ops += 1

    def read_all(self, mount, path):
        self.tick()
        return super().read_all(mount, path)

    def write(self, mount, path, data):
        self.tick()
        super().write(mount, path, data)

    def request(self, method, path, body):
        self.tick()
        return super().request(method, path, body)


def claim_release(bao):
    bao.entries.setdefault(RELEASING, {"at": "now"})


def erase_release(bao):
    for path in (TOKEN, DIGEST, AGENT_KEY):
        bao.entries.pop(path, None)


def converge(bao, planned=None):
    return openbao.converge_secrets(bao, planned or planned_for(), lambda: "m1nted")
