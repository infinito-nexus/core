from __future__ import annotations

import json
import re
import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.compose_volumes import compose_volumes
from plugins.lookup.registry_vendors import registry_of
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any, load_yaml_str
from utils.docker.image.ref import DOCKER_HUB_REGISTRIES
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "svc-registry-cache"
FRONT_CONF = ROLE / "templates" / "front.conf.j2"
VENDOR_ENV = ROLE / "templates" / "vendor.env.j2"
ENV_DIR = "/opt/compose/registry-cache/env/"
TTL = "168h"
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
FRONT_TASKS = ROLE / "tasks" / "utils" / "front.yml"
VENDOR_ENV_TASKS = ROLE / "tasks" / "utils" / "vendor_env.yml"
CONSTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "01_constructor.yml"
VENDORS = ["docker-registry.kixdesk.com", "ghcr.io", "mcr.microsoft.com"]
GATEWAY = "192.168.205.1"
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE")
VOLUMES = load_yaml(str(ROLE / ROLE_FILE_META_VOLUMES))
DATA_TARGET = VOLUMES["data"]["mounts"][0]["target"]
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
    "roles/sys-svc-container/templates/base.yml.j2": (
        "    base: {{ service_name }}\n"
        "{% if docker_compose_env is defined %}\n"
        '    env_file: ["{{ docker_compose_env }}"]\n'
        "{% endif %}\n"
        "\n"
    ),
    "roles/sys-svc-container/templates/env.j2": "TZ=UTC\n",
}
TODAY = (
    "services:\n"
    "  cache:\n"
    '    container_image: [["svc-registry-cache", "cache"], {}]\n'
    '    compose_only: [["container_name", "cache-registry"], {}]\n'
    "    base: cache\n"
    '    container_healthcheck: [["cache"], {}]\n'
    '    container_ports: [[["cache", "registry"]], {}]\n'
    '    container_volumes: [["cache"], {}]\n'
    "    container_networks: [[], {}]\n"
    "\n"
    "compose_volumes: [[], {}]\n"
    "compose_networks: [[], {}]"
)


def _lookup(name, *terms, **kwargs):
    passed = {key: value for key, value in kwargs.items() if value != {}}
    return f"{name}: {json.dumps([list(terms), passed], sort_keys=True)}"


def _environment():
    environment = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    environment.filters.update(CoreFilters().filters())
    environment.filters.update(MathFilters().filters())
    environment.globals["lookup"] = _lookup
    return environment


def _role_var(name):
    expression = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[name]
    return re.fullmatch(r"\{\{\s*(.*?)\s*\}\}", expression).group(1)


def _vendor_services(vendors):
    expression = _environment().compile_expression(
        _role_var("REGISTRY_CACHE_VENDOR_SERVICES")
    )
    return expression(REGISTRY_CACHE_VENDORS=vendors)


def _vendor_env_files(vendors):
    expression = _environment().compile_expression(
        _role_var("REGISTRY_CACHE_VENDOR_ENV_FILES")
    )
    return expression(
        REGISTRY_CACHE_VENDOR_SERVICES=_vendor_services(vendors),
        REGISTRY_CACHE_ENV_DIR=ENV_DIR,
    )


def _vendor_env(vendor):
    return dict(
        line.split("=", 1)
        for line in _environment()
        .from_string(read_text(str(VENDOR_ENV)))
        .render(registry_cache_vendor=vendor, REGISTRY_CACHE_PROXY_TTL=TTL)
        .splitlines()
        if line
    )


def _vendor_env_findings(services, env_files):
    findings = []
    for service, env_file in env_files.items():
        entry = services[service]
        if entry.get("env_file") != [env_file]:
            findings.append(f"{service} binds {entry.get('env_file')}")
        if "environment" in entry:
            findings.append(f"{service} declares environment inline")
    return findings


def _render(path, vendors):
    return (
        _environment()
        .from_string(read_text(str(path)))
        .render(
            application_id="svc-registry-cache",
            entity_name="cache",
            IS_COMPOSE_MODE=True,
            REGISTRY_CACHE_FLAVOR="registry",
            REGISTRY_CACHE_CONTAINER="cache-registry",
            REGISTRY_CACHE_DATA_TARGET=DATA_TARGET,
            REGISTRY_CACHE_VENDORS=vendors,
            REGISTRY_CACHE_VENDOR_SERVICES=_vendor_services(vendors),
            REGISTRY_CACHE_VENDOR_ENV_FILES=_vendor_env_files(vendors),
            REGISTRY_CACHE_VENDOR_PORT=5000,
            REGISTRY_CACHE_FRONT_CONTAINER="cache-registry-front",
            REGISTRY_CACHE_FRONT_HOST=GATEWAY,
            REGISTRY_CACHE_FRONT_LISTEN_PORT=443,
            REGISTRY_CACHE_FRONT_TLS_TARGET="/etc/nginx/tls",
            REGISTRY_CACHE_FRONT_CERT_NAME=f"{GATEWAY}.crt",
            REGISTRY_CACHE_FRONT_KEY_NAME=f"{GATEWAY}.key",
            REGISTRY_CACHE_FRONT_RESOLVER="127.0.0.11",
        )
    )


def _compose(vendors):
    return load_yaml_str(_render(ROLE / ROLE_FILE_TEMPL_COMPOSE, vendors))


def _stub_args(value):
    return json.loads(value) if isinstance(value, str) else value


def _server_lines(vendors):
    return [line.strip() for line in _render(FRONT_CONF, vendors).splitlines()]


def _locations(vendors):
    blocks: dict[str, list[str]] = {}
    current = None
    for line in _server_lines(vendors):
        match = re.fullmatch(r"location (?:= )?(\S+) \{", line)
        if match:
            current = blocks.setdefault(match.group(1), [])
        elif line == "}":
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def _admitted_methods(vendors):
    lines = _server_lines(vendors)
    first_location = next(
        i for i, line in enumerate(lines) if line.startswith("location")
    )
    for index, line in enumerate(lines[:first_location]):
        match = re.fullmatch(r"if \(\$request_method !~ (\S+)\) \{", line)
        if match and lines[index + 1] == "return 405;":
            pattern = re.compile(match.group(1))
            return {method for method in METHODS if pattern.search(method)}
    return set(METHODS)


def _tasks():
    return load_yaml_any(str(CORE_TASKS))


def _vendor_block():
    return next(task for task in _tasks() if "block" in task)


def _front_tasks():
    return load_yaml_any(str(FRONT_TASKS))


class TestWithoutVendors(unittest.TestCase):
    def test_the_compose_render_is_byte_identical_to_today(self):
        self.assertEqual(_render(ROLE / ROLE_FILE_TEMPL_COMPOSE, []), TODAY)

    def test_an_empty_vendor_volume_map_renders_todays_top_level_volumes(self):
        applications = {
            "svc-registry-cache": {
                "services": load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
            }
        }
        self.assertEqual(
            compose_volumes(
                applications,
                "svc-registry-cache",
                extra_volumes={},
                dir_var_lib="/var/lib/infinito",
            ),
            compose_volumes(
                applications, "svc-registry-cache", dir_var_lib="/var/lib/infinito"
            ),
        )

    def test_every_vendor_task_waits_for_a_vendor(self):
        block = _vendor_block()
        self.assertEqual(block["when"], "REGISTRY_CACHE_VENDORS | length > 0")
        self.assertIn(
            "utils/front.yml",
            [task.get("ansible.builtin.include_tasks") for task in block["block"]],
        )
        outside = [task for task in _tasks() if task is not block]
        self.assertFalse(
            any("openssl" in json.dumps(task) for task in outside),
            "a certificate task runs without a vendor",
        )
        cleanup = [task for task in outside if "ansible.builtin.file" in task]
        self.assertEqual(
            [task["when"] for task in cleanup],
            ["REGISTRY_CACHE_VENDORS | length == 0"],
        )
        self.assertEqual(cleanup[0]["ansible.builtin.file"]["state"], "absent")


class TestVendorCaches(unittest.TestCase):
    def test_every_vendor_gets_its_own_cache_service(self):
        services = _compose(VENDORS)["services"]
        self.assertEqual(
            set(services),
            {
                "cache",
                "front",
                "vendor-docker-registry-kixdesk-com",
                "vendor-ghcr-io",
                "vendor-mcr-microsoft-com",
            },
        )
        for vendor, service in _vendor_services(VENDORS).items():
            with self.subTest(vendor=vendor):
                entry = services[service]
                self.assertEqual(entry["env_file"], [f"{ENV_DIR}{service}.env"])
                self.assertEqual(entry["volumes"], [f"{service}:{DATA_TARGET}"])
                self.assertEqual(entry["base"], "vendor")
                self.assertEqual(
                    _stub_args(entry["container_image"]),
                    [["svc-registry-cache", "cache"], {}],
                )

    def test_every_vendor_reads_its_own_env_file_and_declares_no_environment(self):
        services = _compose(VENDORS)["services"]
        self.assertEqual(_vendor_env_findings(services, _vendor_env_files(VENDORS)), [])
        self.assertNotIn("env_file", services["cache"])
        self.assertNotIn("env_file", services["front"])

    def test_negative_control_a_shared_or_inline_vendor_env_is_reported(self):
        services = _compose(VENDORS)["services"]
        env_files = _vendor_env_files(VENDORS)
        first, second = list(env_files)[:2]
        services[first]["env_file"] = [env_files[second]]
        services[second]["environment"] = {"REGISTRY_PROXY_REMOTEURL": "https://x"}
        self.assertEqual(
            _vendor_env_findings(services, env_files),
            [
                f"{first} binds {[env_files[second]]}",
                f"{second} declares environment inline",
            ],
        )

    def test_every_vendor_env_file_proxies_its_own_registry(self):
        for vendor in VENDORS:
            with self.subTest(vendor=vendor):
                self.assertEqual(
                    _vendor_env(vendor),
                    {
                        "TZ": "UTC",
                        "REGISTRY_PROXY_REMOTEURL": f"https://{vendor}",
                        "REGISTRY_PROXY_TTL": TTL,
                    },
                )

    def test_a_loop_task_renders_one_env_file_per_vendor_before_compose(self):
        self.assertIn(
            "utils/vendor_env.yml",
            [
                task.get("ansible.builtin.include_tasks")
                for task in _vendor_block()["block"]
            ],
        )
        tasks = load_yaml_any(str(VENDOR_ENV_TASKS))
        render = next(task for task in tasks if "stack_host_template" in task)
        self.assertEqual(render["stack_host_template"]["src"], "vendor.env.j2")
        self.assertEqual(
            render["stack_host_template"]["dest"],
            "{{ REGISTRY_CACHE_VENDOR_ENV_FILES[registry_cache_vendor_service.value] }}",
        )
        self.assertEqual(
            render["loop"], "{{ REGISTRY_CACHE_VENDOR_SERVICES | dict2items }}"
        )
        self.assertEqual(
            render["vars"]["registry_cache_vendor"],
            "{{ registry_cache_vendor_service.key }}",
        )
        self.assertEqual(render["notify"], "compose-up")
        directory = next(task for task in tasks if "ansible.builtin.file" in task)
        self.assertLess(tasks.index(directory), tasks.index(render))
        self.assertEqual(
            directory["ansible.builtin.file"]["path"], "{{ REGISTRY_CACHE_ENV_DIR }}"
        )
        compose = next(i for i, task in enumerate(_tasks()) if "include_role" in task)
        self.assertLess(_tasks().index(_vendor_block()), compose)

    def test_every_vendor_env_file_lives_in_the_role_env_directory(self):
        self.assertEqual(
            _vendor_env_files(VENDORS),
            {
                service: f"{ENV_DIR}{service}.env"
                for service in _vendor_services(VENDORS).values()
            },
        )

    def test_no_vendor_shares_a_volume_with_docker_hub_or_another_vendor(self):
        compose = _compose(VENDORS)
        extra = _stub_args(compose["compose_volumes"])[1]["extra_volumes"]
        names = [spec["name"] for spec in extra.values()]
        self.assertEqual(len(set(names)), len(VENDORS))
        self.assertNotIn("docker_registry_cache_data", names)
        self.assertEqual(set(extra), set(_vendor_services(VENDORS).values()))

    def test_the_front_binds_the_role_network_gateway(self):
        front = _compose(VENDORS)["services"]["front"]
        self.assertEqual(
            _stub_args(front["container_ports"]),
            [[{"ip": GATEWAY, "protocol": "registry", "service": "front"}], {}],
        )

    def test_the_front_routes_each_vendor_to_its_own_cache(self):
        locations = _locations(VENDORS)
        for vendor, service in _vendor_services(VENDORS).items():
            with self.subTest(vendor=vendor):
                body = locations[f"/v2/{vendor}/"]
                self.assertIn(f"set $vendor_backend {service}:5000;", body)
                rewrite = next(line for line in body if line.startswith("rewrite"))
                pattern = rewrite.split()[1]
                self.assertEqual(
                    re.sub(pattern, r"/v2/\1", f"/v2/{vendor}/foo/bar/manifests/1.0"),
                    "/v2/foo/bar/manifests/1.0",
                )
                self.assertIsNone(re.match(pattern, "/v2/elsewhere/foo/manifests/1.0"))
        self.assertEqual(locations["/"], ["return 404;"])

    def test_the_front_answers_the_registry_ping_itself(self):
        self.assertIn("return 200 '{}';", _locations(VENDORS)["/v2/"])

    def test_the_front_admits_get_and_head_only(self):
        self.assertEqual(_admitted_methods(VENDORS), {"GET", "HEAD"})

    def test_the_certificate_names_the_gateway_and_serves_tls_only(self):
        issue = next(
            task
            for task in _front_tasks()
            if "req" in task.get("ansible.builtin.command", {}).get("argv", [])
        )
        argv = issue["ansible.builtin.command"]["argv"]
        self.assertIn("subjectAltName=IP:{{ REGISTRY_CACHE_FRONT_HOST }}", argv)
        self.assertIn("basicConstraints=critical,CA:FALSE", argv)
        self.assertIn("extendedKeyUsage=serverAuth", argv)
        self.assertEqual(
            _role_var("REGISTRY_CACHE_FRONT_HOST"), "lookup('subnet_gateway')"
        )

    def test_the_certificate_is_trusted_for_its_endpoint_only(self):
        copy = next(
            task["ansible.builtin.copy"]
            for task in _front_tasks()
            if "ansible.builtin.copy" in task
        )
        self.assertEqual(copy["src"], "{{ REGISTRY_CACHE_FRONT_CERT }}")
        self.assertEqual(
            copy["dest"], "{{ [REGISTRY_CACHE_FRONT_TRUST_DIR, 'ca.crt'] | path_join }}"
        )
        self.assertEqual(
            _role_var("REGISTRY_CACHE_FRONT_TRUST_DIR"),
            "['/etc/docker/certs.d', REGISTRY_CACHE_FRONT_ENDPOINT] | path_join",
        )
        self.assertEqual(
            load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))["REGISTRY_CACHE_FRONT_ENDPOINT"],
            "{{ REGISTRY_CACHE_FRONT_HOST }}:{{ REGISTRY_CACHE_FRONT_PORT }}",
        )


class TestBootstrapOrder(unittest.TestCase):
    def test_every_role_bootstrapped_up_to_the_cache_pulls_docker_hub_only(self):
        loop = next(
            task["loop"]
            for task in load_yaml_any(str(CONSTRUCTOR))
            if isinstance(task, dict)
            and isinstance(task.get("loop"), list)
            and "svc-registry" in task["loop"]
        )
        groups = loop[: loop.index("svc-registry") + 1]
        offenders = []
        for services_file in sorted(
            PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_SERVICES}")
        ):
            role = services_file.parent.parent.name
            if not any(role.startswith(f"{group}-") for group in groups):
                continue
            for key, entry in (load_yaml(str(services_file)) or {}).items():
                image = entry.get("image") if isinstance(entry, dict) else None
                registry = registry_of(str(image)) if image else None
                if registry and registry not in DOCKER_HUB_REGISTRIES:
                    offenders.append(f"{role}.{key}: {image}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
