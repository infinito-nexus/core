from __future__ import annotations

import runpy
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.network_of import FilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.reachability import TOR, network, sibling_domain
from utils.roles.mapping import (
    ROLE_FILE_META_SERVER,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "web-app-matrix"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
SERVICES = ROLE_DIR / ROLE_FILE_META_SERVICES
SERVER = ROLE_DIR / ROLE_FILE_META_SERVER
CORE = ROLE_DIR / "tasks/00_core.yml"
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
STACK_VHOSTS = PROJECT_ROOT / "roles/svc-stack/filter_plugins/stack_vhosts.py"
ASSERT_TASK = "✅ assert Jitsi is not requested on an onion-primary homeserver"
JITSI_KEY = f"applications.{ROLE}.services.jitsi.enabled"
PRIMARY = "example.org"
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw" + network(TOR).suffix
CLEARNET_HOMESERVER = f"matrix.{PRIMARY}"
CANONICAL = {
    "synapse": CLEARNET_HOMESERVER,
    "element": f"element.{PRIMARY}",
    "jitsi": f"jitsi.matrix.{PRIMARY}",
}
TOR_ON_ANOTHER_NODE = {
    "group_names": [ROLE],
    "node": NODE,
    "homeserver": sibling_domain(CLEARNET_HOMESERVER, TOR, PRIMARY, NODE),
}
CLEARNET = {"group_names": [ROLE], "node": "", "homeserver": CLEARNET_HOMESERVER}


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


def _yaml(path):
    return load_yaml_str(read_text(path))


class _World:
    def __init__(self, *, group_names, node, homeserver, overrides=None) -> None:
        """
        Args:
            group_names: the inventory groups of the host rendering the role.
            node: the node onion address of the cluster, empty without Tor.
            homeserver: what ``lookup('domain', 'web-app-matrix')`` answers.
            overrides: inventory values per ``services.*`` path of the role,
                answered instead of the meta value.
        """
        self.node = node
        self.homeserver = homeserver
        self.overrides = dict(overrides or {})
        self.environment = NativeEnvironment(
            autoescape=jinja2.select_autoescape(default_for_string=False)
        )
        self.environment.filters.update(FilterModule().filters())
        self.environment.filters["bool"] = _ansible_bool
        self.environment.globals["lookup"] = self.lookup
        self.context = {"application_id": ROLE, "group_names": group_names}
        variables = _yaml(VARS)
        for name in (
            "MATRIX_ONION_NODE",
            "MATRIX_ONION_PRIMARY",
            "MATRIX_JITSI_ENABLED",
        ):
            self.context[name] = self.render(variables[name])

    def render(self, value):
        if not isinstance(value, str) or "{{" not in value:
            return value
        return self.environment.from_string(value).render(self.context)

    def holds(self, conditions) -> bool:
        return all(
            _ansible_bool(
                self.environment.compile_expression(condition)(**self.context)
            )
            for condition in conditions
        )

    def lookup(self, name, *terms):
        if name == "domain" and terms == (ROLE,):
            return self.homeserver
        if name == "config" and terms[:2] == ("svc-net-tor", "services.tor.node"):
            return self.node
        if name == "config" and terms[0] == ROLE and terms[1] in self.overrides:
            return self.overrides[terms[1]]
        if name == "config" and terms[0] == ROLE and terms[1].startswith("services."):
            value = _yaml(SERVICES)
            for part in terms[1].removeprefix("services.").split("."):
                value = value[part]
            return self.render(value)
        raise AssertionError(f"unexpected lookup({name!r}, {terms!r})")

    def vhost_keys(self) -> list[str]:
        declared = {
            key: {name: self.render(value) for name, value in entry.items()}
            for key, entry in _yaml(SERVER)["vhosts"].items()
        }
        stack_vhosts = runpy.run_path(str(STACK_VHOSTS))["stack_vhosts"]
        return [
            vhost["key"] for vhost in stack_vhosts(declared, self.homeserver, CANONICAL)
        ]


class TestJitsiOnionGate(unittest.TestCase):
    def _assertion(self) -> dict:
        task = next(
            (task for task in _yaml(CORE) if task.get("name") == ASSERT_TASK), None
        )
        self.assertIsNotNone(task, f"tasks/00_core.yml has no task {ASSERT_TASK!r}")
        return task["ansible.builtin.assert"]

    def test_an_onion_primary_homeserver_off_the_tor_node_offers_no_jitsi(self):
        world = _World(**TOR_ON_ANOTHER_NODE)

        self.assertIs(
            world.lookup("config", ROLE, "services.jitsi.enabled"),
            False,
            "services.jitsi.enabled reports Jitsi on an onion-primary homeserver",
        )
        self.assertIs(world.context["MATRIX_JITSI_ENABLED"], False)
        self.assertNotIn("jitsi", world.vhost_keys())

    def test_a_literal_jitsi_request_on_that_homeserver_fails_the_assert(self):
        world = _World(
            **TOR_ON_ANOTHER_NODE, overrides={"services.jitsi.enabled": True}
        )
        assertion = self._assertion()

        self.assertFalse(
            world.holds(assertion["that"]),
            "a literal Jitsi request on an onion-primary homeserver passes the assert",
        )
        message = world.render(assertion["fail_msg"])
        self.assertIn("onion-primary Matrix", message)
        self.assertIn(JITSI_KEY, message)

    def test_the_clearnet_default_offers_the_own_jitsi(self):
        world = _World(**CLEARNET)

        self.assertIs(world.lookup("config", ROLE, "services.jitsi.enabled"), True)
        self.assertIs(world.context["MATRIX_JITSI_ENABLED"], True)
        self.assertIn("jitsi", world.vhost_keys())
        self.assertTrue(world.holds(self._assertion()["that"]))


if __name__ == "__main__":
    unittest.main()
