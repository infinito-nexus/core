import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"


def _shim(exists):
    return SimpleNamespace(stat=SimpleNamespace(exists=exists))


def _daemon_json(**overrides):
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    env.filters["to_json"] = json.dumps
    env.globals["lookup"] = lambda name, *_a, **_k: []
    variables = {
        "DEPLOYMENT_MODE": "compose",
        "IS_STACK_HOST": True,
        "DOCKER_IN_CONTAINER": False,
        "DOMAIN_PRIMARY": "infinito.test",
        "KATA_SHIM_BINARY": "/usr/bin/containerd-shim-kata-v2",
        "RUNSC_SHIM_BINARY": "/usr/local/bin/runsc",
        "SANDBOX_RUNTIME": "runsc",
        "SYS_SVC_CONTAINER_DATA_ROOT": "",
        "swarm": {"registry": {"host": "", "port": 5000}},
        "groups": {"svc-registry-cache": []},
        "ansible_facts": {"os_family": "Debian"},
        "SYS_SVC_CONTAINER_DOCKER_FIREWALL_BACKEND_BY_OS_FAMILY": {
            "Debian": "iptables"
        },
        "NETWORK_DOCKER_ADDRESS_POOLS": [{"base": "10.208.0.0/12", "size": 24}],
        "sys_svc_container_kvm": _shim(False),
        "sys_svc_container_kata_shim": _shim(False),
        "sys_svc_container_runsc_shim": _shim(False),
        **overrides,
    }
    return json.loads(env.get_template("daemon.json.j2").render(variables))


class TestUserlandProxy(unittest.TestCase):
    def test_the_daemon_publishes_ports_without_the_userland_proxy(self):
        self.assertIs(_daemon_json()["userland-proxy"], False)

    def test_swarm_and_docker_in_docker_keep_it_off(self):
        parsed = _daemon_json(
            DEPLOYMENT_MODE="swarm", IS_STACK_HOST=False, DOCKER_IN_CONTAINER=True
        )
        self.assertIs(parsed["userland-proxy"], False)


if __name__ == "__main__":
    unittest.main()
