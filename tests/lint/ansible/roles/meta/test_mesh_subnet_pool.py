from __future__ import annotations

import ipaddress
import unittest

import jinja2

from cli.administration.inventory.mesh.inventory import specs_of
from utils.cache.yaml import load_yaml_any
from utils.networks.mesh import (
    APPLICATION_ID,
    HUB_KEY,
    INTERFACES_KEY,
    MESHES_KEY,
    ROAMING_KEY,
)
from utils.roles.deploy import role_has_stack
from utils.roles.mapping import ROLE_FILE_META_NETWORKS

from . import PROJECT_ROOT

NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"
DEVELOPMENT_LAYOUT = PROJECT_ROOT / "inventories" / "development" / "wireguard.yml"
EXAMPLES_DIR = PROJECT_ROOT / "inventories" / "examples"


def layout_files() -> list:
    found = [DEVELOPMENT_LAYOUT] if DEVELOPMENT_LAYOUT.is_file() else []
    found += sorted(EXAMPLES_DIR.glob("*/wireguard.yml"))
    return found


def _applications(path) -> dict:
    return (load_yaml_any(str(path), default_if_missing={}) or {}).get(
        "applications"
    ) or {}


def _pool() -> ipaddress.IPv4Network:
    data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
    pool = data.get("NETWORK_MESH_POOL")
    if isinstance(pool, str) and "{{" in pool:
        pool = jinja2.Template(
            pool, autoescape=jinja2.select_autoescape(default_for_string=False)
        ).render(**data)
    if not isinstance(pool, str):
        raise TypeError(f"{NETWORKS_FILE} must declare NETWORK_MESH_POOL as a string")
    return ipaddress.ip_network(pool, strict=True)


class TestTheRolesShipNoMesh(unittest.TestCase):
    def test_every_mesh_field_a_role_carries_is_empty(self) -> None:
        carried = 0
        for path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_NETWORKS}")
        ):
            networks = load_yaml_any(str(path), default_if_missing={}) or {}
            for key in (MESHES_KEY, INTERFACES_KEY):
                if key not in networks:
                    continue
                carried += 1
                with self.subTest(role=path.parent.parent.name, key=key):
                    self.assertEqual(
                        [],
                        networks[key],
                        f"{path}: networks.{key} must ship empty; the values "
                        "belong to the deployment's inventory",
                    )
        self.assertGreater(carried, 0, "no role carries a mesh field at all")

    def test_every_stack_role_carries_the_membership_field(self) -> None:
        stack_roles = [
            role
            for role in sorted((PROJECT_ROOT / "roles").iterdir())
            if role.is_dir() and role_has_stack(role)
        ]
        self.assertGreater(len(stack_roles), 0, "no stack role found")
        for role in stack_roles:
            networks = load_yaml_any(
                str(role / ROLE_FILE_META_NETWORKS), default_if_missing={}
            )
            with self.subTest(role=role.name):
                self.assertIn(
                    MESHES_KEY,
                    networks or {},
                    f"{role.name}/{ROLE_FILE_META_NETWORKS} must carry "
                    f"networks.{MESHES_KEY}: [] so a compose host can join meshes "
                    "through it",
                )

    def test_the_declaring_role_ships_every_field_empty(self) -> None:
        networks = load_yaml_any(
            str(PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_NETWORKS),
            default_if_missing={},
        )
        self.assertEqual(
            {MESHES_KEY: [], INTERFACES_KEY: [], HUB_KEY: "", ROAMING_KEY: False},
            networks,
        )


class TestTheShippedLayouts(unittest.TestCase):
    def setUp(self) -> None:
        self.files = layout_files()
        if not self.files:
            self.skipTest("the repository ships no WireGuard layout")

    def test_every_declared_mesh_sits_inside_the_pool(self) -> None:
        pool = _pool()
        for path in self.files:
            for spec in specs_of(_applications(path), []):
                with self.subTest(
                    layout=str(path.relative_to(PROJECT_ROOT)), mesh=spec.name
                ):
                    self.assertTrue(
                        ipaddress.ip_network(spec.subnet, strict=True).subnet_of(pool),
                        f"{path}: mesh '{spec.name}' subnet {spec.subnet} sits "
                        f"outside NETWORK_MESH_POOL ({pool})",
                    )

    def test_no_two_meshes_of_one_layout_share_a_listen_port(self) -> None:
        for path in self.files:
            ports = [spec.listen_port for spec in specs_of(_applications(path), [])]
            duplicated = sorted({port for port in ports if ports.count(port) > 1})
            with self.subTest(layout=str(path.relative_to(PROJECT_ROOT))):
                self.assertEqual([], duplicated, f"{path}: shared listen port(s)")

    def test_every_membership_names_a_declared_mesh(self) -> None:
        for path in self.files:
            applications = _applications(path)
            declared = {spec.name for spec in specs_of(applications, [])}
            for role, config in applications.items():
                if role == APPLICATION_ID:
                    continue
                joined = ((config or {}).get("networks") or {}).get(MESHES_KEY) or []
                with self.subTest(
                    layout=str(path.relative_to(PROJECT_ROOT)), role=role
                ):
                    self.assertLessEqual(set(joined), declared)

    def test_the_platform_itself_declares_no_meshes(self) -> None:
        shipped = load_yaml_any(
            str(PROJECT_ROOT / "group_vars" / "all" / "21_wireguard.yml"),
            default_if_missing={},
        )
        self.assertNotIn("WIREGUARD_MESHES", shipped or {})
