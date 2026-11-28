import functools
import glob
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.template import Templar, trust_as_template
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    nodes,
    select_autoescape,
)

from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.config import get as get_app_conf
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

PROMETHEUS_APP_ID = "web-app-prometheus"
ROLES_DIR = PROJECT_ROOT / "roles"

_DOMAIN = "infinito.test"
_MODES = ("compose", "swarm")
_GROUP_NAMES = (
    "web-app-prometheus",
    "web-app-gitea",
    "web-app-matrix",
    "svc-prx-openresty",
)
_INVENTORY_CREDENTIALS = {
    "logout_gate_key": "fixture-logout-gate-key",
    "metricz_bearer": "fixture-metricz-bearer",
}
_INJ_OFF = {
    "logout": False,
    "dashboard": False,
    "css": False,
    "matomo": False,
    "javascript": False,
}
_CONTAINER_NAME_SET = re.compile(
    r'^\s*set \$container_name "([^"]*)";\s*$', re.MULTILINE
)
_LUA_BLOCK_OPEN = re.compile(r"\b([a-z_]+_by_lua_block)\s*\{")
_APP_ID_SET = re.compile(r'^\s*set \$app_id "([^"]*)";\s*$', re.MULTILINE)
_EXACT_LOCATION = re.compile(r"^\s*location = (\S+) \{", re.MULTILINE)
_SHARED_DICT = re.compile(r"^\s*lua_shared_dict\s+(\S+)\s+(\S+);", re.MULTILINE)
_LUA_SHARED_DICT = re.compile(r"\bngx\.shared\.(\w+)")
_LUA_METHOD_CALL = re.compile(r"\b(\w+):(set|collect)\(")
_LUA_CONNECT = re.compile(r'\bsock:connect\("([^"]+)"\)')
_LUA_TIMER = re.compile(r"\bngx\.timer\.(at|every)\((\d+),\s*(\w+)\)")
_LIVE_PROBE_CAPTURE = 'ngx.location.capture("/_live_probe")'
_PROMETHEUS_CONF = "roles/web-app-prometheus/templates/nginx/prometheus.conf.j2"
_CONFIGURATION = ROLES_DIR / PROMETHEUS_APP_ID / "templates" / "configuration"
_METRICS_PORT = 9100
_ALERTMANAGER_UNSET = {
    "ALERTMANAGER_TELEGRAM_BOT_TOKEN": "",
    "ALERTMANAGER_TELEGRAM_CHAT_ID": 0,
    "ALERTMANAGER_MATTERMOST_WEBHOOK_URL": "",
}
_DOCKER_SOCKET = "unix:/var/run/docker.sock"
_DOCKER_PS = {
    "compose": [
        {
            "Names": ["/gitea"],
            "State": "running",
            "Status": "Up 3 minutes (unhealthy)",
            "Labels": {"com.docker.compose.service": "gitea"},
        },
        {
            "Names": ["/prometheus"],
            "State": "running",
            "Status": "Up 2 hours (healthy)",
            "Labels": {"com.docker.compose.service": "prometheus"},
        },
        {
            "Names": ["/matrix-synapse"],
            "State": "running",
            "Status": "Up 5 hours",
            "Labels": None,
        },
    ],
    "swarm": [
        {
            "Names": ["/gitea_gitea.1.k3j2x"],
            "State": "running",
            "Status": "Up 3 minutes (unhealthy)",
            "Labels": {
                "com.docker.stack.namespace": "gitea",
                "com.docker.swarm.service.name": "gitea_gitea",
            },
        },
        {
            "Names": ["/prometheus_prometheus.1.x9q2"],
            "State": "running",
            "Status": "Up 2 hours (healthy)",
            "Labels": {"com.docker.swarm.service.name": "prometheus_prometheus"},
        },
        {
            "Names": ["/matrix_synapse.1.old"],
            "State": "running",
            "Status": "Up 1 hour (unhealthy)",
            "Labels": {"com.docker.swarm.service.name": "matrix_synapse"},
        },
        {
            "Names": ["/matrix_synapse.2.new"],
            "State": "running",
            "Status": "Up 1 hour (healthy)",
            "Labels": {"com.docker.swarm.service.name": "matrix_synapse"},
        },
    ],
}
_LUA_HARNESS = r"""
local dir = arg[1]
local null = newproxy(false)

local function read(name)
  local f = assert(io.open(dir .. "/" .. name))
  local s = f:read("*a")
  f:close()
  return s
end

local body = read("containers.json")
local decoded = assert(loadfile(dir .. "/containers.lua"))(null)

local function world(ptype, connect_err)
  local w = {connects = 0, warns = 0, now = 0, at = {}, every = {}, store = {}, ttl = {}, expires = {}, gauges = {}}
  local function live(k) return w.store[k] ~= nil and (w.expires[k] == 0 or w.expires[k] > w.now) end
  local function metric(name)
    return {
      set = function(_, v) w.gauges[name] = v end,
      inc = function() end,
      observe = function() end,
    }
  end
  local prom = {
    counter = function(_, n) return metric(n) end,
    histogram = function(_, n) return metric(n) end,
    gauge = function(_, n) return metric(n) end,
    collect = function() w.collected = true end,
  }
  local modules = {
    ["ngx.process"] = {
      type = function() return ptype end,
      enable_privileged_agent = function() w.enabled = true return true end,
    },
    ["resty.prometheus"] = {init = function() return prom end},
    ["cjson.safe"] = {decode = function(s) if s == body then return decoded end end},
  }
  local ngx = {
    ERR = 4, WARN = 5, HTTP_OK = 200, HTTP_SERVICE_UNAVAILABLE = 503,
    log = function(level) if level == 5 then w.warns = w.warns + 1 end end,
    header = {},
    var = {},
    shared = {health_containers = {
      set = function(_, k, v, ttl)
        w.store[k] = v w.ttl[k] = ttl w.expires[k] = ttl == 0 and 0 or w.now + ttl
        return true
      end,
      get = function(_, k) if live(k) then return w.store[k] end end,
      get_keys = function()
        local keys = {}
        for k in pairs(w.store) do if live(k) then keys[#keys + 1] = k end end
        return keys
      end,
    }},
    timer = {
      at = function(delay, fn) w.at[#w.at + 1] = delay fn(false) return true end,
      every = function(delay) w.every[#w.every + 1] = delay return true end,
    },
    socket = {tcp = function()
      local lines = {"HTTP/1.0 200 OK", "Api-Version: 1.41", "Content-Type: application/json", ""}
      local n = 0
      return {
        connect = function(_, target)
          w.connects = w.connects + 1 w.target = target
          if connect_err then return nil, connect_err end
          return true
        end,
        send = function(_, data) w.request = data return #data end,
        receive = function(_, pattern)
          if pattern == "*l" then n = n + 1 return lines[n] end
          return body
        end,
        close = function() end,
      }
    end},
    location = {capture = function() return {status = w.probe} end},
    worker = {id = function() if ptype == "worker" then return 0 end end},
  }
  ngx.print = function() end
  w.ngx = ngx
  w.env = setmetatable({ngx = ngx, require = function(name) return assert(modules[name], name) end}, {__index = _G})
  return w
end

local function run(w, name)
  local chunk = assert(loadstring(read(name), name))
  setfenv(chunk, w.env)
  chunk()
end

local master = world("master")
run(master, "init.lua")
print("enabled\t" .. tostring(master.enabled))

local worker = world("worker")
run(worker, "init_worker.lua")
print("worker\t" .. worker.connects .. "/" .. #worker.at .. "/" .. #worker.every)

local agent = world("privileged agent")
run(agent, "init_worker.lua")
print("agent\t" .. tostring(agent.target) .. "\t" .. tostring(agent.request and agent.request:match("^[^\r\n]*")) .. "\t" .. table.concat(agent.at, ",") .. "/" .. table.concat(agent.every, ","))
for key, value in pairs(agent.store) do
  print("dict\t" .. key .. "\t" .. value .. "/" .. agent.ttl[key])
end

local function request(w, key)
  w.ngx.var = {container_name = key, host = "h", app_id = "a"}
  w.probe = 200
  w.ngx.status = nil
  run(w, "live.lua")
  run(w, "metricz.lua")
  return tostring(w.ngx.status), tostring(w.gauges.nginx_stack_up), tostring(w.gauges.nginx_docker_health_entries)
end

for i = 2, #arg do
  local status, up, entries = request(agent, arg[i])
  print("live\t" .. arg[i] .. "\t" .. status)
  print("metricz\t" .. arg[i] .. "\t" .. up .. "\t" .. entries)
end

agent.now = 61
local _, _, expired = request(agent, arg[2])
print("expired\t" .. expired)

local denied = world("privileged agent", "permission denied")
run(denied, "init_worker.lua")
print("denied\t" .. denied.connects .. "\t" .. denied.warns)
for i = 2, #arg do
  local status, up, entries = request(denied, arg[i])
  print("denied_metricz\t" .. arg[i] .. "\t" .. status .. "\t" .. up .. "\t" .. entries)
end

local stale = world("worker")
run(stale, "init_worker.lua")
stale.env.metric_docker_health_entries = nil
local stale_ok = pcall(request, stale, arg[2])
print("stale_conf\t" .. tostring(stale_ok) .. "\t" .. tostring(stale.collected))
"""


def _load_config(file_path: str) -> dict:
    return load_yaml_any(file_path) or {}


def _trusted(value: object) -> object:
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, Mapping):
        return {k: _trusted(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trusted(v) for v in value]
    return value


def _vars_layer(paths: list[Path]) -> dict:
    loaded: dict = {}
    for path in paths:
        if not path.is_file():
            continue
        data = load_yaml_any(str(path), default_if_missing={})
        if isinstance(data, Mapping):
            loaded.update({k: _trusted(v) for k, v in data.items()})
    return loaded


def _render(application_id: str, template: str, mode: str, extra: dict) -> str:
    """Render a template through Ansible's templar with the deploy's own lookups.

    Args:
        application_id: role whose defaults and vars layer over group_vars/all.
        template: template path relative to the repository root.
        mode: DEPLOYMENT_MODE, ``compose`` or ``swarm``.
        extra: variables the including task passes to the template.

    Returns:
        The rendered text.
    """
    source = (PROJECT_ROOT / template).resolve()
    return _template(
        application_id, mode, extra, f"{{{{ lookup('template', '{source}') }}}}"
    )


def _template(application_id: str, mode: str, extra: dict, expression: str) -> str:
    """Evaluate a Jinja expression with the variables a role deploy carries.

    Args:
        application_id: role whose defaults and vars layer over group_vars/all.
        mode: DEPLOYMENT_MODE, ``compose`` or ``swarm``.
        extra: variables layered on top.
        expression: the Jinja source to evaluate.

    Returns:
        The evaluated text.
    """
    applications = get_application_defaults(roles_dir=ROLES_DIR)
    applications[application_id].setdefault("secrets", {}).setdefault(
        "credentials", {}
    ).update(_INVENTORY_CREDENTIALS)
    variables = {
        **_vars_layer(sorted((PROJECT_ROOT / "group_vars" / "all").glob("*.yml"))),
        **_vars_layer(
            [
                ROLES_DIR / application_id / ROLE_FILE_DEFAULTS_MAIN,
                ROLES_DIR / application_id / ROLE_FILE_VARS_MAIN,
            ]
        ),
        "applications": applications,
        "application_id": application_id,
        "group_names": list(_GROUP_NAMES),
        "inventory_hostname": "localhost",
        "RESOURCE_HOST_CPUS_OVERRIDE": 4,
        "RESOURCE_HOST_MEM_MB_OVERRIDE": 8192,
        "playbook_dir": str(PROJECT_ROOT),
        "ansible_search_path": [str(PROJECT_ROOT)],
        "DEPLOYMENT_MODE": mode,
        "TIMEOUT_FACTOR": 1,
        "PRIMARY_DOMAIN": _DOMAIN,
        "DOMAIN_PRIMARY": _DOMAIN,
        "SYSTEM_EMAIL_DOMAIN": _DOMAIN,
        "inj_enabled": _INJ_OFF,
        **extra,
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    return str(templar.template(trust_as_template(expression)))


def _vhost(application_id: str, service_key: str, mode: str, **extra) -> str:
    """Render the vhost include that sets ``$container_name`` for one application.

    Args:
        application_id: the proxied application.
        service_key: the ``services.<key>`` entry whose local http port the vhost proxies.
        mode: DEPLOYMENT_MODE, ``compose`` or ``swarm``.
        extra: further template variables, e.g. ``matrix_flavor``.

    Returns:
        The rendered nginx location block.
    """
    template = (
        "roles/web-app-matrix/templates/synapse.conf.j2"
        if application_id == "web-app-matrix"
        else "roles/web-app-prometheus/templates/nginx/locations.conf.j2"
    )
    http_port = get_app_conf(
        applications=get_application_defaults(roles_dir=ROLES_DIR),
        application_id=application_id,
        config_path=f"services.{service_key}.ports.local.http",
        strict=False,
        default="",
    )
    domain = _template(
        application_id, mode, {}, "{{ lookup('domain', application_id) }}"
    )
    return _render(
        application_id,
        template,
        mode,
        {"http_port": http_port, "domain": domain, **extra},
    )


def _container_name(rendered: str) -> str:
    found = _CONTAINER_NAME_SET.findall(rendered)
    if len(found) != 1:
        raise AssertionError(f"expected one 'set $container_name', found {found!r}")
    return found[0]


def _lua_blocks(rendered: str) -> dict[str, list[str]]:
    """Collect the Lua body of every ``*_by_lua_block`` in rendered nginx config.

    Args:
        rendered: nginx configuration text.

    Returns:
        Directive name mapped to its bodies in document order.
    """
    blocks: dict[str, list[str]] = {}
    consumed = 0
    for match in _LUA_BLOCK_OPEN.finditer(rendered):
        if match.start() < consumed:
            continue
        depth, i, quote = 1, match.end(), None
        while depth:
            ch = rendered[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif rendered.startswith("--", i):
                i = rendered.index("\n", i)
                continue
            elif ch in "\"'":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        consumed = i
        blocks.setdefault(match.group(1), []).append(rendered[match.end() : i - 1])
    return blocks


def _lua_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "{" + ", ".join(_lua_literal(v) for v in value) + "}"
    if isinstance(value, Mapping):
        return (
            "{"
            + ", ".join(
                f"[{json.dumps(k)}] = {_lua_literal(v)}" for k, v in value.items()
            )
            + "}"
        )
    raise TypeError(f"no Lua literal for {type(value).__name__}")


def _harness_outcome(mode: str, keys: list[str]) -> dict:
    """Run the rendered Lua blocks under luajit against a canned Docker answer.

    Args:
        mode: DEPLOYMENT_MODE whose renders and ``_DOCKER_PS`` fixture are used.
        keys: ``$container_name`` values to request ``/healthz/live`` and ``/metricz`` with.

    Returns:
        ``enabled``, ``worker``, ``agent``, ``expired``, ``denied`` and ``stale_conf`` results
        plus the ``dict``, ``live``, ``metricz`` and ``denied_metricz`` maps
        keyed by container key, each value a tuple of the printed fields.
    """
    conf = _lua_blocks(
        _render(
            PROMETHEUS_APP_ID,
            "roles/web-app-prometheus/templates/nginx/prometheus.conf.j2",
            mode,
            {},
        )
    )
    vhost = _lua_blocks(_vhost(PROMETHEUS_APP_ID, "prometheus", mode))
    files = {
        "init.lua": conf["init_by_lua_block"][0],
        "init_worker.lua": conf["init_worker_by_lua_block"][0],
        "live.lua": vhost["content_by_lua_block"][0],
        "metricz.lua": vhost["content_by_lua_block"][-1],
        "containers.json": json.dumps(_DOCKER_PS[mode]),
        "containers.lua": "local null = ...\nreturn "
        + _lua_literal(_DOCKER_PS[mode])
        + "\n",
        "harness.lua": _LUA_HARNESS,
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name, text in files.items():
            (work / name).write_text(text)
        result = subprocess.run(
            ["luajit", str(work / "harness.lua"), str(work), *keys],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise AssertionError(f"luajit failed in {mode}:\n{result.stderr}")
    keyed = ("dict", "live", "metricz", "denied_metricz")
    outcome: dict = {kind: {} for kind in keyed}
    for fields in (line.split("\t") for line in result.stdout.splitlines()):
        if fields[0] in keyed:
            outcome[fields[0]][fields[1]] = tuple(fields[2:])
        else:
            outcome[fields[0]] = fields[1:]
    return outcome


@functools.cache
def _rendered_vhost(
    application_id: str, service_key: str, prometheus_deployed: bool = True
) -> str:
    """
    Args:
        application_id: the proxied application.
        service_key: the ``services.<key>`` entry whose local http port the vhost proxies.
        prometheus_deployed: whether ``web-app-prometheus`` runs on the host.

    Returns:
        The compose-mode monitoring include of the application's vhost.
    """
    groups = [
        group
        for group in _GROUP_NAMES
        if prometheus_deployed or group != PROMETHEUS_APP_ID
    ]
    return _vhost(application_id, service_key, "compose", group_names=groups)


def _location_block(content: str, location: str) -> str:
    """
    Args:
        content: rendered nginx configuration.
        location: the path of an exact-match location.

    Returns:
        The location block, braces included.
    """
    start = content.index(f"location = {location} {{")
    depth = 0
    for index in range(start, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    raise AssertionError(f"unterminated block for {location}")


def _location_lua(content: str, location: str) -> str:
    """
    Args:
        content: rendered nginx configuration.
        location: the path of an exact-match location.

    Returns:
        The body of the location's only content_by_lua_block.
    """
    (body,) = _lua_blocks(_location_block(content, location))["content_by_lua_block"]
    return body


def _poller() -> str:
    """
    Returns:
        The rendered init_worker_by_lua_block that runs the Docker health poller.
    """
    rendered = _render(PROMETHEUS_APP_ID, _PROMETHEUS_CONF, "compose", {})
    (body,) = _lua_blocks(rendered)["init_worker_by_lua_block"]
    return body


def _alertmanager_receiver(channels: tuple[str, ...] = (), **settings: object) -> dict:
    """
    Args:
        channels: what ``lookup('active_alertmanager_channels')`` returns.
        settings: ``ALERTMANAGER_*`` variables the inventory sets.

    Returns:
        The ``default`` receiver of the rendered alertmanager.yml.
    """
    answers = {
        "email": {
            "host": f"mail.{_DOMAIN}",
            "port": 465,
            "from": f"alerts@{_DOMAIN}",
            "domain": _DOMAIN,
            "tls": True,
            "auth": False,
        },
        "users": {"email": f"administrator@{_DOMAIN}", "secondary_email": ""},
        "active_alertmanager_channels": list(channels),
    }
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    env.filters["bool"] = CoreFilters().filters()["bool"]
    env.globals["lookup"] = lambda name, *_args: answers[name]
    rendered = env.from_string(
        read_text(str(_CONFIGURATION / "alertmanager.yml.j2"))
    ).render(application_id=PROMETHEUS_APP_ID, **{**_ALERTMANAGER_UNSET, **settings})
    return next(
        receiver
        for receiver in load_yaml_str(rendered)["receivers"]
        if receiver["name"] == "default"
    )


def _native_scrape_jobs(app_ids: tuple[str, ...]) -> list[dict]:
    """
    Args:
        app_ids: what ``lookup('native_metrics_apps')`` returns.

    Returns:
        The scrape jobs the native-metrics loop of prometheus.yml renders
        through each application's own fragment.
    """
    lines = read_text(str(_CONFIGURATION / "prometheus.yml.j2")).splitlines()
    start = next(
        i for i, row in enumerate(lines) if "lookup('native_metrics_apps')" in row
    )
    end = next(
        i for i in range(start, len(lines)) if lines[i].strip() == "{% endfor %}"
    )

    def lookup(name, *args):
        if name == "native_metrics_apps":
            return list(app_ids)
        if name == "native_metrics_target":
            return f"{args[0]}:{_METRICS_PORT}"
        if name == "config":
            return args[2]
        raise AssertionError(f"unexpected lookup({name!r}, ...)")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    env.globals["lookup"] = lookup
    source = "scrape_configs:\n" + "\n".join(lines[start : end + 1])
    return load_yaml_str(env.from_string(source).render())["scrape_configs"] or []


class TestPrometheusServicePresence(unittest.TestCase):
    """
    All web-app-* and web-svc-* roles (except web-app-prometheus itself) must
    declare the shared prometheus service in their services section:

        prometheus:
          enabled: true
          shared: true

    This enables the prometheus role to discover them via the
    service_should_load lookup plugin.
    """

    def _web_role_configs(self):
        roles_dir = ROLES_DIR
        pattern = str(roles_dir / "*" / ROLE_FILE_META_SERVICES)
        return [
            p
            for p in sorted(glob.glob(pattern))  # nocheck: project-walk
            if (
                Path(p).parts[-3].startswith(("web-app-", "web-svc-"))
                and Path(p).parts[-3] != PROMETHEUS_APP_ID
            )
        ]

    def test_all_web_roles_have_prometheus_service(self):
        """Every web-app-* and web-svc-* role must have services.prometheus."""
        configs = self._web_role_configs()
        self.assertTrue(configs, "No web-app-*/web-svc-* meta/services.yml files found")

        errors = []
        for file_path in configs:
            role_name = Path(file_path).parts[-3]
            try:
                cfg = _load_config(file_path)
            except yaml.YAMLError as exc:
                errors.append(f"{role_name}: YAML parse error: {exc}")
                continue

            services = cfg or {}
            prom = services.get("prometheus")

            if prom is None:
                errors.append(
                    f"{role_name}: services.prometheus is missing. "
                    f"Add:\n    prometheus:\n      enabled: true\n      shared: true"
                )
                continue

            if not isinstance(prom, dict):
                errors.append(
                    f"{role_name}: services.prometheus must be a mapping, got {type(prom).__name__}"
                )
                continue

            if not is_explicit_truth(prom.get("enabled")):
                errors.append(
                    f"{role_name}: services.prometheus.enabled must be true "
                    f"(literal or `\"{{{{ '<role>' in group_names }}}}\"`), "
                    f"got {prom.get('enabled')!r}"
                )

            if not is_explicit_truth(prom.get("shared")):
                errors.append(
                    f"{role_name}: services.prometheus.shared must be true "
                    f"(literal or `\"{{{{ '<role>' in group_names }}}}\"`), "
                    f"got {prom.get('shared')!r}"
                )

        if errors:
            self.fail(
                f"Prometheus service configuration violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def test_prometheus_role_has_image_config(self):
        """web-app-prometheus must define image, version, and name for its service."""
        roles_dir = ROLES_DIR
        config_path = roles_dir / PROMETHEUS_APP_ID / ROLE_FILE_META_SERVICES

        self.assertTrue(config_path.exists(), f"Missing: {config_path}")

        cfg = _load_config(str(config_path))
        svc = cfg or {}
        prom = svc.get("prometheus") or {}

        for key in ("image", "version", "name"):
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    prom,
                    f"web-app-prometheus: services.prometheus.{key} is not set",
                )
                self.assertTrue(
                    prom[key],
                    f"web-app-prometheus: services.prometheus.{key} must not be empty",
                )

    def test_alert_rules_mounted_in_prometheus_container(self):
        """meta/volumes.yml must declare a mount that lands the rendered
        alert_rules.yml inside the Prometheus container, otherwise the
        file is materialised on disk but never loaded and all alerts are
        dead. Accepts either type:bind (compose mode) or type:config
        (swarm-distributed, the file-bind-should-be-config canonical).
        """
        roles_dir = ROLES_DIR
        meta_path = roles_dir / PROMETHEUS_APP_ID / ROLE_FILE_META_VOLUMES
        entries = load_yaml_any(str(meta_path), default_if_missing={})
        self.assertIsInstance(
            entries,
            dict,
            "web-app-prometheus must use the canonical dict-of-dicts meta/volumes.yml",
        )
        alert_rules_mounts = [
            mount
            for semantic_name, entry in entries.items()
            if isinstance(entry, dict) and entry.get("type") in ("bind", "config")
            for mount in entry.get("mounts") or []
            if isinstance(mount, dict)
            and mount.get("target") == "/etc/prometheus/alert_rules.yml"
        ]
        self.assertTrue(
            alert_rules_mounts,
            "meta/volumes.yml must declare a type:bind or type:config entry "
            "whose mount target is /etc/prometheus/alert_rules.yml so the "
            "rendered alert rules file is loaded by the container.",
        )


class TestPrometheusNginxEndpoints(unittest.TestCase):
    """
    The shared nginx vhost template must expose /healthz/live and /healthz/ready.

    Two prometheus templates are conditionally included to follow SRP:
    - location.conf.j2  — log_by_lua_block for per-request metrics; on every app vhost
                          with services.prometheus.enabled = true
    - metricz.conf   — location = /metricz scrape endpoint; ONLY on the prometheus
                          domain (services.prometheus.name is set)
                          Restricting /metricz to one domain prevents leaking the full
                          metrics payload from every app's public hostname.
    """

    def _basic_conf_path(self):
        return (
            PROJECT_ROOT
            / "roles"
            / "sys-svc-proxy"
            / "templates"
            / "vhost"
            / "basic.conf.j2"
        )

    def test_basic_conf_has_health_endpoints(self):
        locations = _EXACT_LOCATION.findall(_rendered_vhost("web-app-gitea", "gitea"))
        for endpoint in ("/healthz/live", "/healthz/ready"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(locations.count(endpoint), 1)

    def test_basic_conf_live_probe_uses_lua(self):
        live = _location_block(
            _rendered_vhost("web-app-gitea", "gitea"), "/healthz/live"
        )
        body = _location_lua(live, "/healthz/live")
        self.assertNotRegex(
            live.replace(body, ""),
            r"(?m)^\s*return\s",
            "/healthz/live must answer from its Lua check, never a static return",
        )

    def test_metricz_conf_exposes_stack_up_gauge(self):
        calls = _LUA_METHOD_CALL.findall(
            _location_lua(_rendered_vhost(PROMETHEUS_APP_ID, "prometheus"), "/metricz")
        )
        self.assertLess(
            calls.index(("metric_stack_up", "set")),
            calls.index(("prometheus", "collect")),
            "/metricz must set the stack_up gauge before it collects the metrics",
        )

    def test_metricz_conf_stack_up_checks_docker_health(self):
        body = _location_lua(
            _rendered_vhost(PROMETHEUS_APP_ID, "prometheus"), "/metricz"
        )
        self.assertEqual(set(_LUA_SHARED_DICT.findall(body)), {"health_containers"})
        self.assertLess(
            body.index("ngx.shared.health_containers"),
            body.index(_LIVE_PROBE_CAPTURE),
            "stack_up must reflect the Docker HEALTHCHECK before HTTP reachability",
        )

    def test_ready_probe_returns_only_the_backend_status(self):
        content = _rendered_vhost("web-app-gitea", "gitea")
        ready = _location_block(content, "/healthz/ready")
        self.assertNotIn(
            "proxy_pass",
            ready,
            "/healthz/ready sits outside the vhost's auth gate; proxying it "
            "hands the client's method, query and body to the backend and "
            "its page back",
        )
        self.assertIn('ngx.location.capture("/_ready_probe")', ready)
        probe = _location_block(content, "/_ready_probe")
        self.assertIn("internal;", probe)
        self.assertIn("proxy_pass", probe)

    def test_basic_conf_delegates_prometheus_to_shared_include(self):
        tree = Environment(
            autoescape=select_autoescape(default_for_string=False)
        ).parse(read_text(str(self._basic_conf_path())))
        unconditional = {
            node.template.value
            for node in tree.body
            if isinstance(node, nodes.Include)
            and isinstance(node.template, nodes.Const)
        }
        self.assertIn(
            "roles/web-app-prometheus/templates/nginx/locations.conf.j2",
            unconditional,
            "every vhost basic.conf.j2 renders must include the shared "
            "monitoring block, outside any condition",
        )

    def test_prometheus_conf_includes_location_conf_for_all_prometheus_apps(self):
        self.assertEqual(
            len(
                _lua_blocks(_rendered_vhost("web-app-gitea", "gitea"))[
                    "log_by_lua_block"
                ]
            ),
            1,
        )
        self.assertEqual(
            _rendered_vhost(
                "web-app-gitea", "gitea", prometheus_deployed=False
            ).strip(),
            "",
        )

    def test_prometheus_conf_includes_metricz_only_on_prometheus_domain(self):
        self.assertNotIn(
            "/metricz",
            _EXACT_LOCATION.findall(_rendered_vhost("web-app-gitea", "gitea")),
            "/metricz on an app vhost leaks the metrics of every application "
            "from that public hostname",
        )

    def test_metricz_conf_has_metricz_endpoint(self):
        self.assertEqual(
            _EXACT_LOCATION.findall(
                _rendered_vhost(PROMETHEUS_APP_ID, "prometheus")
            ).count("/metricz"),
            1,
        )

    def test_basic_conf_sets_app_id_variable(self):
        self.assertEqual(
            _APP_ID_SET.findall(_rendered_vhost("web-app-gitea", "gitea")),
            ["web-app-gitea"],
            "the metrics of a vhost carry its application as the 'app' label",
        )

    def test_alertmanager_templates_exist(self):
        """web-app-prometheus must have alertmanager.yml.j2 and alert_rules.yml.j2."""
        roles_dir = ROLES_DIR
        for template in ("alertmanager.yml.j2", "alert_rules.yml.j2"):
            with self.subTest(template=template):
                path = (
                    roles_dir
                    / PROMETHEUS_APP_ID
                    / "templates"
                    / "configuration"
                    / template
                )
                self.assertTrue(
                    path.exists(),
                    f"Missing alertmanager template: {path}",
                )

    def test_alertmanager_supports_telegram(self):
        receiver = _alertmanager_receiver(
            ALERTMANAGER_TELEGRAM_BOT_TOKEN="fixture-bot-token",
            ALERTMANAGER_TELEGRAM_CHAT_ID="4242",
        )
        self.assertEqual(
            [
                (config["bot_token"], config["chat_id"])
                for config in receiver["telegram_configs"]
            ],
            [("fixture-bot-token", 4242)],
        )
        self.assertNotIn("telegram_configs", _alertmanager_receiver())

    def test_alertmanager_supports_mattermost(self):
        webhook = f"https://mattermost.{_DOMAIN}/hooks/fixture"
        receiver = _alertmanager_receiver(
            ("web-app-mattermost",), ALERTMANAGER_MATTERMOST_WEBHOOK_URL=webhook
        )
        self.assertEqual(
            [config["api_url"] for config in receiver["slack_configs"]], [webhook]
        )
        self.assertNotIn(
            "slack_configs",
            _alertmanager_receiver(ALERTMANAGER_MATTERMOST_WEBHOOK_URL=webhook),
            "a webhook without a deployed Mattermost channel must not be notified",
        )

    def test_alert_rules_has_communication_channel_rule(self):
        """alert_rules.yml.j2 must have a rule targeting communication-channel apps specifically.

        The task AC requires alert rules for communication channels (Mattermost, Matrix, Mailu).
        Generic AppDown alone is insufficient — a dedicated rule makes intent explicit and allows
        different routing/escalation for communication-critical apps.

        Channel list is discovered dynamically via the active_alertmanager_channels lookup plugin.
        Each app self-declares communication.channel: true in its own config (SPOT per app —
        no hardcoded list anywhere).
        """
        roles_dir = ROLES_DIR
        content = read_text(
            str(
                roles_dir
                / PROMETHEUS_APP_ID
                / "templates"
                / "configuration"
                / "alert_rules.yml.j2"
            )
        )
        self.assertIn(
            "CommunicationChannelDown",
            content,
            "alert_rules.yml.j2 must define a CommunicationChannelDown alert rule "
            "(task AC: alert rules for communication channels — Mattermost, Matrix, Mailu)",
        )
        self.assertIn(
            "active_alertmanager_channels",
            content,
            "CommunicationChannelDown must use the active_alertmanager_channels lookup plugin "
            "for dynamic channel discovery (no hardcoded list)",
        )
        for app_id in ("web-app-mattermost", "web-app-matrix"):
            with self.subTest(app_id=app_id):
                cfg = _load_config(str(roles_dir / app_id / ROLE_FILE_META_SERVICES))
                prometheus_cfg = cfg.get("prometheus", {})
                self.assertTrue(
                    (prometheus_cfg.get("communication") or {}).get("channel") is True,
                    f"{app_id}/meta/services.yml must declare "
                    f"services.prometheus.communication.channel: true "
                    f"so the active_alertmanager_channels plugin discovers it",
                )


class TestDockerHealthCheck(unittest.TestCase):
    """
    /healthz/live must check Docker container health in addition to HTTP reachability.
    HTTP-reachability alone is insufficient — a container can be "running" in Docker
    while its HEALTHCHECK has flipped to "unhealthy".
    """

    def _basic_conf_path(self):
        return (
            PROJECT_ROOT
            / "roles"
            / "sys-svc-proxy"
            / "templates"
            / "vhost"
            / "basic.conf.j2"
        )

    def _openresty_compose_path(self):
        return PROJECT_ROOT / "roles" / "svc-prx-openresty" / ROLE_FILE_TEMPL_COMPOSE

    def test_nginx_conf_has_health_containers_dict(self):
        rendered = _render(PROMETHEUS_APP_ID, _PROMETHEUS_CONF, "compose", {})
        self.assertEqual(
            sorted(dict(_SHARED_DICT.findall(rendered))),
            ["health_containers", "prometheus_metrics"],
            "/healthz/live and /metricz read Docker health from the "
            "health_containers shared dict the poller writes, next to the "
            "metrics dict lua-resty-prometheus keeps",
        )

    def test_nginx_conf_polls_docker_socket(self):
        self.assertEqual(_LUA_CONNECT.findall(_poller()), [_DOCKER_SOCKET])

    def test_nginx_conf_timer_runs_at_startup_and_periodically(self):
        self.assertEqual(
            _LUA_TIMER.findall(_poller()),
            [("at", "0", "poll_docker_health"), ("every", "15", "poll_docker_health")],
        )

    def test_basic_conf_live_probe_checks_docker_health(self):
        body = _location_lua(_rendered_vhost("web-app-gitea", "gitea"), "/healthz/live")
        self.assertEqual(_LUA_SHARED_DICT.findall(body), ["health_containers"])
        self.assertLess(
            body.index("ngx.shared.health_containers"),
            body.index(_LIVE_PROBE_CAPTURE),
            "/healthz/live must consult Docker health before the HTTP sub-request",
        )

    def test_openresty_compose_mounts_docker_socket(self):
        """svc-prx-openresty meta/volumes.yml must declare a read-only bind
        of /var/run/docker.sock into the openresty service, so the Lua
        background timer can query Docker container health. Post-canonical-
        migration this lives in meta, not compose.yml.j2 — the mount surface
        emerges via `lookup('container_volumes', ...)`.
        """
        meta_path = (
            PROJECT_ROOT / "roles" / "svc-prx-openresty" / ROLE_FILE_META_VOLUMES
        )
        entries = load_yaml_any(str(meta_path), default_if_missing={})
        self.assertIsInstance(
            entries,
            dict,
            "svc-prx-openresty must use the canonical dict-of-dicts meta/volumes.yml",
        )
        docker_sock_binds = [
            mount
            for semantic_name, entry in entries.items()
            if isinstance(entry, dict)
            and entry.get("type") == "bind"
            and str(entry.get("source", "")).strip() == "/var/run/docker.sock"
            for mount in entry.get("mounts") or []
            if isinstance(mount, dict)
            and mount.get("service") == "openresty"
            and str(mount.get("target", "")).strip() == "/var/run/docker.sock"
        ]
        self.assertTrue(
            docker_sock_binds,
            "svc-prx-openresty meta/volumes.yml must declare a "
            "type:bind entry with source=/var/run/docker.sock and a mount "
            "into service 'openresty' at target=/var/run/docker.sock so the "
            "Lua background timer can query Docker container health.",
        )


class TestDockerHealthKey(unittest.TestCase):
    CASES = (
        ("web-app-gitea", "gitea", {}, "gitea"),
        (PROMETHEUS_APP_ID, "prometheus", {}, "prometheus"),
        ("web-app-matrix", "synapse", {"matrix_flavor": "compose"}, "synapse"),
        ("web-app-matrix", "synapse", {"matrix_flavor": "ansible"}, "matrix"),
    )

    def test_key_is_the_name_docker_reports_in_each_mode(self):
        applications = get_application_defaults(roles_dir=ROLES_DIR)
        for application_id, port_key, extra, docker_key in self.CASES:
            expected = {
                "compose": get_app_conf(
                    applications=applications,
                    application_id=application_id,
                    config_path=f"services.{docker_key}.name",
                ),
                "swarm": f"{entity_name(application_id)}_{docker_key}",
            }
            for mode in _MODES:
                with self.subTest(application_id=application_id, mode=mode, **extra):
                    self.assertEqual(
                        expected[mode],
                        _container_name(
                            _vhost(application_id, port_key, mode, **extra)
                        ),
                    )


@unittest.skipUnless(shutil.which("luajit"), "luajit runs the rendered Lua blocks")
class TestDockerHealthLuaRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = {
            mode: {
                "unhealthy": _container_name(_vhost("web-app-gitea", "gitea", mode)),
                "healthy": _container_name(
                    _vhost(PROMETHEUS_APP_ID, "prometheus", mode)
                ),
                "mixed": _container_name(
                    _vhost("web-app-matrix", "synapse", mode, matrix_flavor="compose")
                ),
                "unknown": "not-on-this-node",
            }
            for mode in _MODES
        }
        cls.outcomes = {
            mode: _harness_outcome(mode, list(cls.keys[mode].values()))
            for mode in _MODES
        }

    def test_init_enables_the_privileged_agent(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertEqual(["true"], self.outcomes[mode]["enabled"])

    def test_request_workers_never_touch_the_docker_socket(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertEqual(["0/0/0"], self.outcomes[mode]["worker"])

    def test_privileged_agent_polls_the_docker_socket(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    [
                        _DOCKER_SOCKET,
                        "GET /v1.41/containers/json HTTP/1.0",
                        "0/15",
                    ],
                    self.outcomes[mode]["agent"],
                )

    def test_poller_stores_state_under_the_key_the_vhost_reads(self):
        for mode in _MODES:
            keys = self.keys[mode]
            with self.subTest(mode=mode):
                self.assertEqual(
                    {
                        keys["unhealthy"]: ("down/60",),
                        keys["healthy"]: ("up/60",),
                        keys["mixed"]: ("up/60",),
                    },
                    {
                        key: self.outcomes[mode]["dict"].get(key)
                        for key in (keys["unhealthy"], keys["healthy"], keys["mixed"])
                    },
                )

    def test_live_and_stack_up_report_an_unhealthy_container_down(self):
        for mode in _MODES:
            keys = self.keys[mode]
            outcome = self.outcomes[mode]
            with self.subTest(mode=mode):
                self.assertEqual(
                    {
                        keys["unhealthy"]: ("503", "0"),
                        keys["healthy"]: ("200", "1"),
                        keys["mixed"]: ("200", "1"),
                        keys["unknown"]: ("200", "1"),
                    },
                    {
                        key: (outcome["live"][key][0], outcome["metricz"][key][0])
                        for key in keys.values()
                    },
                )

    def test_entries_gauge_counts_the_unexpired_dict_entries(self):
        for mode in _MODES:
            outcome = self.outcomes[mode]
            with self.subTest(mode=mode):
                self.assertGreater(len(outcome["dict"]), 0)
                self.assertEqual(
                    {str(len(outcome["dict"]))},
                    {fields[1] for fields in outcome["metricz"].values()},
                )

    def test_entries_gauge_drops_to_zero_once_the_poller_stops(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertEqual(["0"], self.outcomes[mode]["expired"])

    def test_entries_gauge_is_zero_when_the_socket_is_denied(self):
        for mode in _MODES:
            keys = self.keys[mode]
            outcome = self.outcomes[mode]
            with self.subTest(mode=mode):
                self.assertEqual(["1", "1"], outcome["denied"])
                self.assertEqual(
                    dict.fromkeys(keys.values(), ("200", "1", "0")),
                    outcome["denied_metricz"],
                )

    def test_metricz_still_collects_before_the_gauge_is_registered(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertEqual(["true", "true"], self.outcomes[mode]["stale_conf"])


class TestNativeAppMetrics(unittest.TestCase):
    """
    Applications that provide native Prometheus metrics MUST have a scrape job
    in prometheus.yml.j2 (task AC: expose /metrics for apps that support it).
    The jobs are guarded by native_metrics.enabled in each app's own config
    (NOT by services.prometheus.enabled which is the nginx integration flag).
    """

    def _scrape_job(self, app_id: str) -> dict:
        (job,) = _native_scrape_jobs((app_id,))
        self.assertEqual(
            job["static_configs"],
            [{"targets": [f"{app_id}:{_METRICS_PORT}"], "labels": {"app": app_id}}],
        )
        return job

    def test_prometheus_yml_uses_native_metrics_apps_lookup(self):
        self.assertEqual(
            [
                job["job_name"]
                for job in _native_scrape_jobs(("web-app-gitea", "web-app-matrix"))
            ],
            ["gitea", "matrix-synapse"],
        )
        self.assertEqual(_native_scrape_jobs(()), [])

    def test_gitea_has_scrape_fragment(self):
        self.assertEqual(self._scrape_job("web-app-gitea")["job_name"], "gitea")

    def test_mattermost_has_scrape_fragment(self):
        self.assertEqual(
            self._scrape_job("web-app-mattermost")["job_name"], "mattermost"
        )

    def test_matrix_has_scrape_fragment(self):
        self.assertEqual(
            self._scrape_job("web-app-matrix")["job_name"], "matrix-synapse"
        )

    def test_native_metrics_apps_have_enabled_flag_in_config(self):
        """Apps with native metrics support must have native_metrics.enabled in their config."""
        roles_dir = ROLES_DIR
        for app_id in ("web-app-gitea", "web-app-mattermost", "web-app-matrix"):
            with self.subTest(app_id=app_id):
                cfg = _load_config(str(roles_dir / app_id / ROLE_FILE_META_SERVICES))
                native_metrics_cfg = cfg.get("prometheus", {}).get("native_metrics", {})
                self.assertTrue(
                    bool(native_metrics_cfg),
                    f"{app_id}/meta/services.yml must have a "
                    f"services.prometheus.native_metrics section "
                    f"(guards the Prometheus scrape job; set enabled: true in inventory to activate)",
                )
                self.assertIn(
                    "enabled",
                    native_metrics_cfg,
                    f"{app_id}/meta/services.yml services.prometheus.native_metrics "
                    f"must have an 'enabled' key",
                )

    def test_gitea_scrape_fragment_uses_metrics_path(self):
        self.assertEqual(self._scrape_job("web-app-gitea")["metrics_path"], "/metrics")

    def test_matrix_scrape_fragment_uses_synapse_metrics_path(self):
        self.assertEqual(
            self._scrape_job("web-app-matrix")["metrics_path"], "/_synapse/metrics"
        )


if __name__ == "__main__":
    unittest.main()
