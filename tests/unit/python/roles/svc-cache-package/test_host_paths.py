from __future__ import annotations

import importlib
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule as ContainerPorts
from utils.cache.yaml import load_yaml_any, load_yaml_str

render = importlib.import_module("tests.unit.python.roles.svc-cache-package._render")

DIR_CACHE = "/var/cache/infinito/core/cache"
DATA = f"{DIR_CACHE}/package/data"
CA = f"{DIR_CACHE}/package/frontend/ca"
CERTS = f"{DIR_CACHE}/package/frontend/certs"
NEXUS_DATA = "/nexus-data"
NEXUS_UID = "200"
TASKS = render.ROLE / "tasks" / "00_core.yml"
FILE_MODULE = "ansible.builtin.file"
INFRA = {
    "package": {"data_path": DATA},
    "frontend": {
        "ca_path": CA,
        "certs_path": CERTS,
        "ports": {"local": {"http": 80, "https": 443}},
    },
}
PORTS_LINE = "container_ports: "


def _volumes(service: str, override=None) -> list:
    return load_yaml_str(render.mounts(service, override))["volumes"]


def _frontend_terms(override=None) -> list:
    return render.role_var(render.environment(override), "CACHE_PACKAGE_FRONTEND_PORTS")


def _published(override) -> str:
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader:
        loader.get.return_value.run.return_value = [render.applications(override)]
        return ContainerPorts().run(
            [["frontend", "http"], ["frontend", "https"]],
            variables={
                "application_id": render.APPLICATION_ID,
                "DEPLOYMENT_MODE": "compose",
            },
        )[0]


def _frontend_ports(compose: str) -> list:
    block = load_yaml_str(compose)["services"]["frontend"]
    return block["container_ports"][0] if "container_ports" in block else []


def _data_dir(override=None) -> tuple[int, dict, dict]:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The position of the role task that prepares the Nexus data directory,
        the task, and its ``path``, ``owner``, ``group`` and ``when`` resolved
        with the role's variables.
    """
    built = render.environment(override)
    values = {
        name: render.role_var(built, name)
        for name in ("CACHE_PACKAGE_DATA_PATH", "CACHE_PACKAGE_DOCKER_USER_ID")
    }
    found = [
        (index, task)
        for index, task in enumerate(load_yaml_any(str(TASKS)))
        if "loop" not in task
        and FILE_MODULE in task
        and built.from_string(task[FILE_MODULE]["path"]).render(**values)
        == values["CACHE_PACKAGE_DATA_PATH"]
    ]
    index, task = found[0]
    resolved = {
        key: built.from_string(str(task[FILE_MODULE][key])).render(**values)
        for key in ("path", "owner", "group")
    }
    resolved["when"] = built.compile_expression(task["when"])(**values)
    return index, task, resolved


def _compose_up_index() -> int:
    return next(
        index
        for index, task in enumerate(load_yaml_any(str(TASKS)))
        if task.get("include_role", {}).get("name") == "sys-svc-compose"
        and task.get("vars", {}).get("compose_handlers_flush") is True
    )


class TestWithoutTheKeys(unittest.TestCase):
    def test_every_render_is_byte_identical_to_today(self) -> None:
        self.assertEqual(render.renders(), render.fixture())

    def test_the_infra_keys_break_the_identity(self) -> None:
        rendered = render.renders(INFRA)
        today = render.fixture()
        for key in (
            "compose",
            "certs_env",
            "mounts_package",
            "mounts_bootstrap",
            "mounts_frontend",
        ):
            with self.subTest(render=key):
                self.assertNotEqual(rendered[key], today[key])

    def test_the_role_publishes_no_frontend_port(self) -> None:
        self.assertEqual(_frontend_terms(), [])
        self.assertEqual(_frontend_ports(render.compose()), [])


class TestDataPath(unittest.TestCase):
    def test_nexus_and_bootstrap_bind_the_data_path(self) -> None:
        for service in ("package", "bootstrap"):
            with self.subTest(service=service):
                self.assertIn(f"{DATA}:{NEXUS_DATA}", _volumes(service, INFRA))
                self.assertNotIn(f"data:{NEXUS_DATA}", _volumes(service, INFRA))

    def test_without_the_key_both_keep_the_named_volume(self) -> None:
        for service in ("package", "bootstrap"):
            with self.subTest(service=service):
                self.assertIn(f"data:{NEXUS_DATA}", _volumes(service))
                self.assertNotIn(f"{DATA}:{NEXUS_DATA}", _volumes(service))


class TestDataOwner(unittest.TestCase):
    def test_the_bound_data_path_is_created_for_the_nexus_uid(self) -> None:
        _, task, resolved = _data_dir(INFRA)
        self.assertIn(f"{resolved['path']}:{NEXUS_DATA}", _volumes("package", INFRA))
        self.assertEqual(task[FILE_MODULE]["state"], "directory")
        self.assertEqual((resolved["owner"], resolved["group"]), (NEXUS_UID, NEXUS_UID))
        self.assertTrue(resolved["when"])

    def test_the_named_volume_leaves_the_host_alone(self) -> None:
        self.assertFalse(_data_dir()[2]["when"])

    def test_the_directory_exists_before_compose_starts_nexus(self) -> None:
        self.assertLess(_data_dir(INFRA)[0], _compose_up_index())


class TestFrontendPaths(unittest.TestCase):
    def test_the_frontend_mounts_the_configured_ca_and_certs(self) -> None:
        volumes = _volumes("frontend", INFRA)
        self.assertIn(f"{CA}:/etc/nginx/ca:ro", volumes)
        self.assertIn(f"{CERTS}:/etc/nginx/certs:ro", volumes)

    def test_the_issuer_writes_into_the_configured_directories(self) -> None:
        env = load_yaml_str(render.certs_env(INFRA))
        self.assertEqual(env["INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR"], CA)
        self.assertEqual(env["INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR"], CERTS)

    def test_without_the_keys_neither_lands_on_the_cache_base(self) -> None:
        env = load_yaml_str(render.certs_env())
        self.assertNotIn(DIR_CACHE, render.mounts("frontend"))
        self.assertNotIn(DIR_CACHE, env["INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR"])
        self.assertNotIn(DIR_CACHE, env["INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR"])


class TestFrontendPorts(unittest.TestCase):
    def test_the_declared_local_ports_reach_the_frontend(self) -> None:
        expected = [["frontend", "http"], ["frontend", "https"]]
        self.assertEqual(sorted(map(list, _frontend_terms(INFRA))), expected)
        self.assertEqual(sorted(_frontend_ports(render.compose(INFRA))), expected)

    def test_the_frontend_publishes_80_and_443(self) -> None:
        self.assertEqual(
            _published(INFRA).splitlines(),
            ["ports:", '  - "80:80"', '  - "443:443"'],
        )

    def test_without_local_ports_the_frontend_has_nothing_to_publish(self) -> None:
        with self.assertRaises(AnsibleError):
            _published(None)


if __name__ == "__main__":
    unittest.main()
