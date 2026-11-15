from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import unittest
from urllib.parse import urlparse

from ansible.errors import AnsibleFilterError

from tests.utils.ansible_assert import assert_task, evaluate, holds
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_README,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-proxmox"
_SPEC = importlib.util.spec_from_file_location(
    "proxmox_role_filters", ROLE / "filter_plugins" / "proxmox_cohosted.py"
)
_FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FILTERS)
proxmox_cohosted = _FILTERS.proxmox_cohosted
proxmox_package_pins = _FILTERS.proxmox_package_pins

SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={})
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
VARIANTS = load_yaml_any(str(ROLE / ROLE_FILE_META_VARIANTS), default_if_missing=[])
DOCKERFILE = read_text(str(ROLE / "files" / "Dockerfile"))
COMPOSE = read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
README = read_text(str(ROLE / ROLE_FILE_README))
TASKS = ROLE / "tasks" / "00_core.yml"
TASK_LIST = load_yaml_any(str(TASKS), default_if_missing=[])
GUARD = ROLE / "tasks" / "utils" / "stack" / "guard.yml"
PROXMOX = SERVICES["proxmox"]
SSO_GATE = assert_task(
    GUARD, "🛑 Refuse to serve the hypervisor UI without the SSO group gate"
)
NO_ONION = assert_task(
    GUARD, "🛑 Refuse to publish the hypervisor UI on an onion address"
)
COHOST = assert_task(
    GUARD, "🛑 Refuse a host that also runs the identity, gateway or vault role"
)


def _list_after(key: str) -> list[str]:
    block = re.search(rf"^\s*{key}:\n((?:\s+- .+\n)+)", COMPOSE, re.MULTILINE)
    return [line.strip()[2:] for line in block.group(1).splitlines()] if block else []


def _readme_section(title: str) -> str:
    match = re.search(
        rf"^## {title}\n(.*?)(?=^## |\Z)", README, re.MULTILINE | re.DOTALL
    )
    return match.group(1) if match else ""


def _include(target: str) -> dict:
    for task in TASK_LIST:
        if target in str(task.get("ansible.builtin.include_tasks", "")):
            return task
    raise AssertionError(f"00_core.yml does not include {target}")


def _sso(group_names: list[str], groups: dict) -> bool:
    expression = SERVICES["sso"]["enabled"].strip()[2:-2]
    return bool(evaluate(expression, {"group_names": group_names, "groups": groups}))


class TestImage(unittest.TestCase):
    def test_base_is_the_official_debian_image(self):
        self.assertEqual(PROXMOX["image"], "debian")
        self.assertTrue(PROXMOX["custom"])
        self.assertTrue(DOCKERFILE.startswith("ARG PROXMOX_BASE_IMAGE"))

    def test_packages_come_from_the_official_no_subscription_repository(self):
        self.assertEqual(
            urlparse(PROXMOX["ve"]["repository"]).hostname, "download.proxmox.com"
        )
        self.assertEqual(
            urlparse(PROXMOX["ve"]["keyring"]).hostname, "enterprise.proxmox.com"
        )
        self.assertIn("Components: pve-no-subscription", DOCKERFILE)
        self.assertNotIn("pve-enterprise", DOCKERFILE)

    def test_every_package_is_pinned_or_the_build_refuses(self):
        packages = PROXMOX["ve"]["packages"]
        self.assertEqual(
            set(packages), {"pve-manager", "pve-cluster", "pve-qemu-kvm", "qemu-server"}
        )
        self.assertRegex(str(packages["pve-manager"]), r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            proxmox_package_pins({"b": "", "a": "1.0"}), "a=1.0 b=", "unpinned keeps ="
        )
        self.assertIn("grep -Eq '^[a-z0-9][a-z0-9.+-]*=[0-9A-Za-z.+~:-]+$'", DOCKERFILE)
        self.assertIn(
            "install -y --no-install-recommends ${PROXMOX_PACKAGES}", DOCKERFILE
        )

    def test_a_version_outside_the_debian_alphabet_is_refused(self):
        for version in ("9.1.1 evil-pkg", "9.1.1;rm", "9.1.1\nevil", "$(id)"):
            with self.assertRaises(AnsibleFilterError, msg=repr(version)):
                proxmox_package_pins({"pve-manager": version})
        self.assertEqual(
            proxmox_package_pins({"a": "1:2.0~rc1+deb13-1"}), "a=1:2.0~rc1+deb13-1"
        )

    def test_dockerfile_check_refuses_smuggled_and_unpinned_words(self):
        line = next(
            line for line in DOCKERFILE.splitlines() if "for pin in" in line
        ).strip()
        script = line.removeprefix("&& ").removesuffix(" \\")
        for pins, code in (
            ("a=1.0 b=2.0", 0),
            ("a=1.0 evil-pkg", 1),
            ("a=1.0 b=", 1),
        ):
            result = subprocess.run(
                ["sh", "-c", script],
                env={"PROXMOX_PACKAGES": pins, "PATH": os.environ["PATH"]},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, code, pins)

    def test_keyring_is_checked_against_its_sha512(self):
        self.assertIn('test -n "${PROXMOX_KEYRING_SHA512}"', DOCKERFILE)
        self.assertIn("sha512sum -c -", DOCKERFILE)
        self.assertIn("keyring_sha512", PROXMOX["ve"])

    def test_no_subscription_workaround(self):
        for needle in (
            "proxmoxlib.js",
            "No valid subscription",
            "subscription.js",
            "sed ",
        ):
            self.assertNotIn(needle, DOCKERFILE)

    def test_every_build_argument_is_passed(self):
        for arg in re.findall(r"^ARG (\w+)$", DOCKERFILE, re.MULTILINE):
            self.assertIn(f"{arg}:", COMPOSE, arg)


class TestModes(unittest.TestCase):
    def test_compose_only(self):
        self.assertTrue(PROXMOX["modes"]["compose"]["enabled"])
        self.assertFalse(PROXMOX["modes"]["swarm"]["enabled"])


class TestGrants(unittest.TestCase):
    def test_every_device_and_capability_has_a_reason(self):
        reasons = _readme_section("Devices, capabilities and namespaces")
        grants = _list_after("devices") + _list_after("cap_add")
        self.assertTrue(grants)
        for grant in grants:
            self.assertRegex(reasons, rf"\*\*`{re.escape(grant)}`:\*\* \S", grant)
        self.assertIn("**`cgroup: private`:**", reasons)
        self.assertIn("**Host namespaces:** none", reasons)
        self.assertIn("userns-remap", reasons)
        self.assertIn("8006 as `127.0.0.1:7992`", reasons)

    def test_no_host_namespace_and_not_privileged(self):
        for forbidden in (
            "privileged:",
            "network_mode:",
            "pid:",
            "ipc:",
            "userns_mode:",
        ):
            self.assertNotIn(forbidden, COMPOSE)

    def test_readme_names_the_websocket_gap_and_no_longer_the_tls_one(self):
        gaps = _readme_section("Known gaps")
        self.assertIn("websocket", gaps)
        self.assertNotIn("TLS upstream", gaps)
        self.assertIn("**HTTPS upstream:**", _readme_section("Features"))


HOSTVARS = {
    "pve": {"ansible_host": "10.0.0.5"},
    "idp": {"ansible_host": "10.0.0.6"},
    "idp-alias": {"ansible_host": "10.0.0.5"},
}


class TestSeparateHost(unittest.TestCase):
    def _peers(self, groups: dict) -> list[str]:
        return proxmox_cohosted(
            VARS["PROXMOX_EXCLUSIVE_PEERS"], "pve", groups, HOSTVARS
        )

    def _holds(self, peers: list[str], shared: bool) -> bool:
        return holds(
            COHOST, {"PROXMOX_COHOSTED_PEERS": peers, "PROXMOX_SHARED_HOST": shared}
        )

    def test_vars_use_the_address_aware_filter(self):
        self.assertIn("proxmox_cohosted(", VARS["PROXMOX_COHOSTED_PEERS"])

    def test_dedicated_host_passes(self):
        peers = self._peers({"web-app-proxmox": ["pve"], "web-app-keycloak": ["idp"]})
        self.assertEqual(peers, [])
        self.assertTrue(self._holds(peers, False))

    def test_each_exclusive_peer_in_own_groups_is_refused(self):
        for peer in ("web-app-keycloak", "svc-ai-litellm", "web-app-openbao"):
            peers = self._peers({"web-app-proxmox": ["pve"], peer: ["pve"]})
            self.assertEqual(peers, [peer])
            self.assertFalse(self._holds(peers, False), peer)

    def test_peer_on_another_inventory_name_of_the_same_machine_is_refused(self):
        peers = self._peers({"web-app-keycloak": ["idp-alias"]})
        self.assertEqual(peers, ["web-app-keycloak"])
        self.assertFalse(self._holds(peers, False))

    def test_other_spellings_of_the_same_machine_are_refused(self):
        for pve, idp in (
            ({"ansible_host": "localhost"}, {"ansible_host": "127.0.0.1"}),
            ({"ansible_host": "::1"}, {"ansible_host": "0:0:0:0:0:0:0:1"}),
            ({"ansible_host": "2001:db8::5"}, {"ansible_host": "2001:DB8:0::5"}),
            (
                {"ansible_host": "Host.Example.com"},
                {"ansible_host": "host.example.com"},
            ),
            (
                {"ansible_host": "host.example.com"},
                {"ansible_host": "host.example.com."},
            ),
            ({"ansible_connection": "local"}, {"ansible_connection": "local"}),
            ({"ansible_connection": "local"}, {"ansible_host": "127.0.0.1"}),
        ):
            found = proxmox_cohosted(
                VARS["PROXMOX_EXCLUSIVE_PEERS"],
                "pve",
                {"web-app-keycloak": ["idp"]},
                {"pve": pve, "idp": idp},
            )
            self.assertEqual(found, ["web-app-keycloak"], (pve, idp))

    def test_different_addresses_stay_separate(self):
        found = proxmox_cohosted(
            VARS["PROXMOX_EXCLUSIVE_PEERS"],
            "pve",
            {"web-app-keycloak": ["idp"]},
            {
                "pve": {"ansible_host": "2001:db8::5"},
                "idp": {"ansible_host": "2001:db8::6"},
            },
        )
        self.assertEqual(found, [])

    def test_shared_host_flag_accepts_the_peers(self):
        self.assertTrue(self._holds(["web-app-keycloak"], True))

    def test_shared_host_defaults_to_false(self):
        self.assertIs(PROXMOX["shared_host"], False)


class TestGates(unittest.TestCase):
    def test_sso_turns_on_when_keycloak_runs_on_another_host(self):
        self.assertTrue(_sso(["web-app-proxmox"], {"web-app-keycloak": ["idp"]}))
        self.assertTrue(_sso(["web-app-proxmox", "web-app-keycloak"], {}))
        self.assertFalse(_sso(["web-app-proxmox"], {"web-app-keycloak": []}))
        self.assertFalse(_sso(["web-app-proxmox"], {}))
        self.assertEqual(SERVICES["sso"]["enabled"], SERVICES["sso"]["shared"])

    def test_deploy_without_the_sso_gate_is_refused(self):
        self.assertFalse(holds(SSO_GATE, {"PROXMOX_SSO_ENABLED": False}))
        self.assertTrue(holds(SSO_GATE, {"PROXMOX_SSO_ENABLED": True}))
        self.assertIn("services.sso.enabled", VARS["PROXMOX_SSO_ENABLED"])

    def test_onion_exposure_is_refused(self):
        self.assertFalse(holds(NO_ONION, {"PROXMOX_TOR_ENABLED": True}))
        self.assertTrue(holds(NO_ONION, {"PROXMOX_TOR_ENABLED": False}))
        self.assertIn("services.tor.enabled", VARS["PROXMOX_TOR_ENABLED"])

    def test_no_variant_requests_the_onion(self):
        self.assertIs(SERVICES["tor"]["enabled"], False)
        self.assertIs(SERVICES["tor"]["shared"], False)
        for variant in VARIANTS:
            self.assertNotIn("tor", variant["services"])

    def test_gates_are_the_stack_guard_and_not_the_role_flow(self):
        names = {task.get("name", "") for task in TASK_LIST}
        for gate in (SSO_GATE, NO_ONION, COHOST):
            self.assertNotIn(gate["name"], names)


class TestHostChecks(unittest.TestCase):
    def test_kvm_is_required(self):
        task = _include("svc-virt-kata/tasks/utils/assert/kvm.yml")
        self.assertEqual(task["vars"]["assert_kvm_consumer"], "{{ application_id }}")

    def test_container_limits_are_proven_against_the_vm_demand(self):
        task = _include("svc-ai-agent-broker/tasks/utils/vm/capacity.yml")
        self.assertEqual(task["vars"]["vm_capacity_kind"], "proxmox")
        self.assertEqual(task["vars"]["vm_capacity_limits"], "{{ PROXMOX_LIMITS }}")
        self.assertIn("services.proxmox.cpus", VARS["PROXMOX_LIMITS"]["cpus"])
        self.assertIn("services.proxmox.mem_limit", VARS["PROXMOX_LIMITS"]["mem_limit"])
        self.assertEqual(
            set(PROXMOX["agents"]["overhead"]), {"cpus", "memory"}, "overhead shape"
        )

    def test_vm_disks_and_template_base_disks_are_left_out_of_the_backup(self):
        volumes = load_yaml_any(
            str(ROLE / ROLE_FILE_META_VOLUMES), default_if_missing={}
        )
        self.assertIs(volumes["proxmox_vm_disks"]["backup"], False)
        self.assertNotIn("backup", volumes["proxmox_config"])
        self.assertNotIn("backup", volumes["proxmox_templates"])
        self.assertIn("base disks of the agent VM templates", README)


CSP = load_yaml_any(str(ROLE / ROLE_FILE_META_CSP), default_if_missing={})
PLAYWRIGHT_ENV = read_text(str(ROLE / "templates" / "playwright.env.j2"))
ADMIN_SPEC = read_text(
    str(ROLE / "files" / "playwright" / "test-administrator-persona.js")
)


def _persona_blocked(env_text: str, persona: str) -> bool:
    return bool(re.search(rf"(?m)^PERSONA_{persona}_BLOCKED=true$", env_text))


class TestLogin(unittest.TestCase):
    def test_pveproxy_is_reached_over_https_behind_the_oauth2_gate(self):
        self.assertEqual(PROXMOX["upstream_scheme"], "https")
        self.assertEqual(PROXMOX["ports"]["internal"]["http"], 8006)
        self.assertEqual(SERVICES["sso"]["flavor"], "oauth2")

    def test_the_realm_uses_the_shared_client_and_is_the_default(self):
        config = VARS["PROXMOX_REALM_CONFIG"]
        self.assertEqual(config["issuer-url"], "{{ OIDC.CLIENT.ISSUER_URL }}")
        self.assertEqual(config["client-id"], "{{ OIDC.CLIENT.ID }}")
        self.assertEqual(config["username-claim"], "{{ OIDC.ATTRIBUTES.USERNAME }}")
        self.assertEqual((config["autocreate"], config["default"]), (1, 1))
        self.assertNotIn("client-key", config)
        self.assertEqual(VARS["PROXMOX_OIDC_CLIENT_SECRET"], "{{ OIDC.CLIENT.SECRET }}")
        self.assertEqual(VARS["PROXMOX_ADMIN_ROLE"], "Administrator")
        self.assertEqual(
            VARS["PROXMOX_ADMIN_GROUP"], "{{ application_id }}-administrator"
        )

    def test_access_follows_the_stack_and_the_sync_follows_access(self):
        names = [task.get("name", "") for task in TASK_LIST]
        access = names.index(_include("01_access.yml")["name"])
        sync_task = _include("tasks/utils/rbac/sync.yml")
        self.assertGreater(
            access, names.index("🚿 Flush compose for {{ application_id }}")
        )
        self.assertGreater(names.index(sync_task["name"]), access)
        sync = sync_task["vars"]
        self.assertEqual(sync["rbac_sync_roles"], ["administrator"])
        self.assertEqual(
            sync["rbac_sync_env"]["PROXMOX_GROUP"], "{{ PROXMOX_ADMIN_GROUP }}"
        )
        self.assertEqual(
            sync["rbac_sync_members_env"],
            [
                {
                    "name": "PROXMOX_RBAC_ADMINISTRATORS",
                    "role": "administrator",
                    "field": "",
                }
            ],
        )
        self.assertIn("files/perl/rbac.pl", sync["rbac_sync_script"])

    def test_csp_opens_only_what_ext_js_needs(self):
        self.assertEqual(
            CSP["flags"],
            {
                "script-src": {"unsafe-eval": True},
                "script-src-elem": {"unsafe-inline": True},
            },
        )

    def test_administrator_persona_runs_and_biber_stays_blocked(self):
        self.assertFalse(_persona_blocked(PLAYWRIGHT_ENV, "ADMINISTRATOR"))
        self.assertTrue(_persona_blocked(PLAYWRIGHT_ENV, "BIBER"))
        self.assertIn("runProxmoxAdminFlow(page)", ADMIN_SPEC)
        self.assertNotIn("runAdminFlow", ADMIN_SPEC)

    def test_negative_control_a_restored_administrator_block_is_seen(self):
        self.assertTrue(
            _persona_blocked(
                PLAYWRIGHT_ENV + "PERSONA_ADMINISTRATOR_BLOCKED=true\n", "ADMINISTRATOR"
            )
        )


if __name__ == "__main__":
    unittest.main()
