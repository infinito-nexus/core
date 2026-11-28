from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from jinja2.nativetypes import NativeEnvironment

from cli.administration.deploy.swarm.closure import is_swarm_inventory
from cli.meta.ci.query import row_modes
from cli.meta.roles.applications.complexity.model import (
    TESTED_LIFECYCLES,
    compute_variant_complexity_rows,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS
from utils.tests.swarm import deploy as swarm_deploy
from utils.tests.swarm import extend_inventory as ei
from utils.tests.swarm import proxmox_host

PROXMOX_ROLE = PROJECT_ROOT / "roles" / proxmox_host.PROXMOX_APP
PEERS = proxmox_host.peers()
LAB_COMPOSE = PROJECT_ROOT / "compose" / "swarm" / "compose.yml"
PROVISION = (
    PROJECT_ROOT / "scripts/tests/deploy/swarm/routine/02_provision_inventory.sh"
)
SWARM_VARS = PROJECT_ROOT / "group_vars" / "all" / "18_swarm.yml"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"
KEYCLOAK = "web-app-keycloak"
PVE = ei.PROXMOX_HOST
TOPOLOGY = (
    "MGR=mgr\nWRK1=wrk1\nWRK2=wrk2\nNFS_SERVER=nfs\nBACKUP_NODE=backup\n"
    "PROXMOX_NODE=pve\n"
)
MANAGER_VARS = "manager: true\n"
PROVISION_STUB = (
    "#!/usr/bin/env bash\n"
    'case "$2" in\n'
    "utils.tests.swarm.derive_includes) echo web-app-proxmox ;;\n"
    "cli.administration.inventory.provision)\n"
    '\tmkdir -p "$3/host_vars"\n'
    f"\tprintf '{MANAGER_VARS}' >\"$3/host_vars/mgr.yml\"\n"
    "\t;;\n"
    "esac\n"
)

_spec = importlib.util.spec_from_file_location(
    "proxmox_cohosted", PROXMOX_ROLE / "filter_plugins" / "proxmox_cohosted.py"
)
_filters = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_filters)


def _groups_of(children: dict, host: str) -> list[str]:
    return sorted(
        group
        for group, body in children.items()
        if host in ((body or {}).get("hosts") or {})
    )


def _groups(children: dict) -> dict[str, list[str]]:
    return {
        group: list((body or {}).get("hosts") or {}) for group, body in children.items()
    }


def _cohosted(children: dict, host: str) -> list[str]:
    hostvars = {
        name: facts
        for body in children.values()
        for name, facts in (((body or {}).get("hosts") or {}).items())
    }
    return _filters.proxmox_cohosted(PEERS, host, _groups(children), hostvars)


def _swarm_facts(children: dict, host: str) -> dict:
    """
    Args:
        children: the ``all.children`` of the inventory the host's play reads.
        host: the inventory host.

    Returns:
        ``DEPLOYMENT_MODE`` and ``IS_STACK_HOST`` as group_vars/all/18_swarm.yml
        resolves them for the host.
    """
    swarm_vars = load_yaml_any(str(SWARM_VARS))
    env = NativeEnvironment()
    facts = {"groups": _groups(children), "inventory_hostname": host}
    for name in ("DEPLOYMENT_MODE", "IS_COMPOSE_MODE", "IS_STACK_HOST"):
        facts[name] = env.from_string(swarm_vars[name].strip()).render(**facts)
    return facts


class _Round(unittest.TestCase):
    def _round(self, flavor: str) -> Path:
        """
        Args:
            flavor: the proxmox flavor the round's variant sets.

        Returns:
            The round's inventory directory after extend_inventory ran.
        """
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        inv_dir = Path(scratch.name)
        closure = [proxmox_host.PROXMOX_APP, *PEERS]
        seeded = {group: {"hosts": {ei._MANAGER: {}}} for group in closure}
        ei.dump_yaml(str(inv_dir / "devices.yml"), {"all": {"children": seeded}})
        (inv_dir / "host_vars").mkdir()
        ei.dump_yaml(
            str(inv_dir / "host_vars" / f"{PVE}.yml"),
            {"NETWORK_MODE": "multi", "keep": 1},
        )
        env = {
            "SWARM_NAME": "t",
            "APP_ID": proxmox_host.PROXMOX_APP,
            "INV_PATH": str(inv_dir / "devices.yml"),
            "INFINITO_SWARM_VPN": "",
        }
        applications = {
            proxmox_host.PROXMOX_APP: {"services": {"proxmox": {"flavor": flavor}}}
        }
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(ei, "derive_includes", return_value=closure),
            mock.patch.object(ei, "get_role_placement", return_value=""),
            mock.patch.object(ei, "applications_for_round", return_value=applications),
        ):
            ei.main()
        return inv_dir

    @staticmethod
    def _children(path: Path) -> dict:
        return load_yaml_any(str(path))["all"]["children"]


class TestProxmoxHost(_Round):
    def test_the_container_row_spans_two_hosts(self) -> None:
        inv_dir = self._round(proxmox_host.DEDICATED_FLAVOR)
        cluster = self._children(inv_dir / "devices.yml")
        sibling = self._children(inv_dir / proxmox_host.INVENTORY)
        self.assertEqual(_groups_of(cluster, PVE), [])
        self.assertNotIn(proxmox_host.PROXMOX_APP, cluster)
        self.assertEqual(_groups_of(sibling, PVE), [proxmox_host.PROXMOX_APP])
        self.assertIn(ei._MANAGER, cluster[KEYCLOAK]["hosts"])
        self.assertEqual(list(sibling[KEYCLOAK]["hosts"]), [ei._MANAGER])
        self.assertNotIn(PVE, (ei._MANAGER, *ei._WORKERS))
        self.assertEqual(_cohosted(sibling, PVE), [])

    def test_the_proxmox_host_resolves_to_compose_mode(self) -> None:
        inv_dir = self._round(proxmox_host.DEDICATED_FLAVOR)
        facts = _swarm_facts(self._children(inv_dir / proxmox_host.INVENTORY), PVE)
        self.assertEqual(facts["DEPLOYMENT_MODE"], "compose")
        self.assertIs(facts["IS_STACK_HOST"], True)
        self.assertTrue(is_swarm_inventory(str(inv_dir / "devices.yml")))
        self.assertFalse(is_swarm_inventory(str(inv_dir / proxmox_host.INVENTORY)))

    def test_negative_control_one_inventory_runs_the_host_in_swarm_mode(self) -> None:
        inv_dir = self._round(proxmox_host.DEDICATED_FLAVOR)
        merged = self._children(inv_dir / "devices.yml")
        merged[proxmox_host.PROXMOX_APP] = {"hosts": {PVE: {}}}
        facts = _swarm_facts(merged, PVE)
        self.assertEqual(facts["DEPLOYMENT_MODE"], "swarm")
        self.assertIs(facts["IS_STACK_HOST"], False)

    def test_the_proxmox_host_keeps_no_swarm_network_mode(self) -> None:
        inv_dir = self._round(proxmox_host.DEDICATED_FLAVOR)
        self.assertEqual(
            load_yaml_any(str(inv_dir / "host_vars" / f"{PVE}.yml")), {"keep": 1}
        )

    def test_negative_control_the_vm_row_stays_on_the_cluster(self) -> None:
        inv_dir = self._round("vm")
        cluster = self._children(inv_dir / "devices.yml")
        self.assertFalse((inv_dir / proxmox_host.INVENTORY).exists())
        self.assertIn(ei._MANAGER, cluster[proxmox_host.PROXMOX_APP]["hosts"])
        self.assertEqual(sorted(_cohosted(cluster, ei._MANAGER)), sorted(PEERS))

    def test_negative_control_a_peer_on_the_proxmox_host_is_refused(self) -> None:
        children = {KEYCLOAK: {"hosts": {"pve": {}}}}
        with self.assertRaisesRegex(ValueError, KEYCLOAK):
            proxmox_host.split_off_proxmox_host(
                children, proxmox_host.PROXMOX_APP, "pve", {}
            )


class TestProxmoxHostDeploy(_Round):
    def _deploy(self, inv_dir: Path, **flags) -> mock.Mock:
        with mock.patch.object(swarm_deploy, "run_step", return_value=0) as step:
            rc = swarm_deploy.deploy_proxmox_host(
                app_id=proxmox_host.PROXMOX_APP,
                inv_dir=str(inv_dir),
                extras_path=str(inv_dir / "extras.yml"),
                round_index=1,
                **flags,
            )
        self.assertEqual(rc, 0)
        return step

    def test_the_dedicated_cli_deploys_the_host_alone(self) -> None:
        inv_dir = self._round(proxmox_host.DEDICATED_FLAVOR)
        argv = self._deploy(inv_dir).call_args.kwargs["cmd"]
        self.assertEqual(argv[2], "cli.administration.deploy.dedicated")
        self.assertEqual(argv[3], str(inv_dir / proxmox_host.INVENTORY))
        self.assertEqual(argv[argv.index("--limit") + 1], PVE)
        self.assertIn("VARIANT_INDEX=1", argv)
        self.assertNotIn("DEPLOY_IS_UPDATE=true", argv)
        update = self._deploy(inv_dir, update_pass=True).call_args.kwargs["cmd"]
        self.assertIn("DEPLOY_IS_UPDATE=true", update)

    def test_negative_control_a_round_without_the_host_deploys_nothing(self) -> None:
        self.assertFalse(self._deploy(self._round("vm")).called)


class TestProxmoxRow(unittest.TestCase):
    rows: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = compute_variant_complexity_rows(
            PROJECT_ROOT / "roles", lifecycles={*TESTED_LIFECYCLES, "pre-alpha"}
        )

    def _row(self, name: str, variant: int):
        (row,) = [r for r in self.rows if r.name == name and r.variant == variant]
        return row

    def test_the_container_variant_gets_a_swarm_row_only(self) -> None:
        variants = load_yaml_any(str(PROXMOX_ROLE / ROLE_FILE_META_VARIANTS))
        flavors = [v["services"]["proxmox"]["flavor"] for v in variants]
        for index, flavor in enumerate(flavors):
            with self.subTest(variant=index, flavor=flavor):
                modes = row_modes(self._row(proxmox_host.PROXMOX_APP, index)._asdict())
                expected = (
                    ("swarm",)
                    if flavor == proxmox_host.DEDICATED_FLAVOR
                    else ("compose",)
                )
                self.assertEqual(modes, expected)

    def test_negative_control_no_other_swarm_off_role_gets_a_swarm_row(self) -> None:
        leaked = sorted(
            f"{r.name}#{r.variant}"
            for r in self.rows
            if r.name != proxmox_host.PROXMOX_APP and not r.swarm and r.test_swarm
        )
        self.assertEqual(leaked, [])

    def test_a_swarm_row_runs_the_lab_routine(self) -> None:
        steps = load_yaml_any(str(WORKFLOW))["jobs"]["deploy"]["steps"]
        (step,) = [s for s in steps if "00_one.sh" in str(s.get("run", ""))]
        self.assertEqual(step["if"], "${{ matrix.mode == 'swarm' }}")


class TestProxmoxLab(unittest.TestCase):
    def test_only_a_container_variant_brings_the_host_up(self) -> None:
        self.assertEqual(
            proxmox_host.profiles(proxmox_host.PROXMOX_APP), [proxmox_host.PROFILE]
        )
        self.assertEqual(proxmox_host.profiles(KEYCLOAK), [])

    def test_the_host_is_a_lab_service_behind_its_own_profile(self) -> None:
        (service,) = [
            body
            for body in load_yaml_any(str(LAB_COMPOSE))["services"].values()
            if "PROXMOX_NODE" in str(body.get("container_name"))
        ]
        self.assertEqual(service["profiles"], [proxmox_host.PROFILE])
        self.assertIn(
            "INFINITO_SWARM_PROXMOX_IP", service["networks"]["lab"]["ipv4_address"]
        )

    def test_the_host_gets_the_host_vars_of_the_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("routine", "utils", "bin"):
                (root / folder).mkdir()
            script = root / "routine" / PROVISION.name
            script.symlink_to(PROVISION)
            (root / "utils" / "_context.sh").write_text(TOPOLOGY, encoding="utf-8")
            stub = root / "bin" / "python3"
            stub.write_text(PROVISION_STUB, encoding="utf-8")
            stub.chmod(0o755)
            inventory = root / "inv"
            done = subprocess.run(
                ["bash", str(script)],
                env={
                    "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
                    "INFINITO_INVENTORY_DIR": str(inventory),
                    "INFINITO_INVENTORY_VARS_FILE": "vars.yml",
                    "INFINITO_GHCR_MIRROR": "false",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                read_text(str(inventory / "host_vars" / "pve.yml")), MANAGER_VARS
            )


if __name__ == "__main__":
    unittest.main()
