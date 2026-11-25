from __future__ import annotations

import importlib
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule as ContainerPorts
from utils import infra_inventory
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_any, load_yaml_str
from utils.env.handlers.infinito.cache.conf import KEY as FRONTEND_CONF_KEY

render = importlib.import_module("tests.unit.python.roles.svc-cache-package._render")

DIR_CACHE = "/var/cache/infinito/core/cache"
DATA = f"{DIR_CACHE}/package/data"
CA = f"{DIR_CACHE}/package/frontend/ca"
CERTS = f"{DIR_CACHE}/package/frontend/certs"
PINNED_MAP = "/home/me/.local/share/infinito/cache/upstreams.conf"
NEXUS_DATA = "/nexus-data"
NEXUS_UID = "200"
TASKS = render.ROLE / "tasks" / "00_core.yml"
FILE_MODULE = "ansible.builtin.file"
COMMAND_MODULE = "ansible.builtin.command"
WAIT_ARGV = ["container", "wait"]
NO_SUCH = "Error response from daemon: No such container: package-cache-bootstrap"
DAEMON_DOWN = "Cannot connect to the Docker daemon. Is the docker daemon running?"
INFRA = {
    "package": {"data_path": DATA},
    "frontend": {
        "ca_path": CA,
        "certs_path": CERTS,
        "map_path": PINNED_MAP,
        "ports": {"local": {"http": 80, "https": 443}},
    },
}
PORTS_LINE = "container_ports: "
MAP_TARGET = "/etc/nginx/conf.d/upstreams.conf"


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


def _mounted_map(override=None) -> str:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The host file the frontend mounts at its map target.
    """
    mounts = load_yaml_str(render.mounts("frontend", override))["configs"]
    [entry] = [mount for mount in mounts if mount["target"] == MAP_TARGET]
    return load_yaml_str(render.top_volumes(override))["configs"][entry["source"]][
        "file"
    ]


def _infra_services(env: dict[str, str]) -> dict:
    """Args:
        env: the environment ``make infra-up`` renders the infra inventory from.

    Returns:
        The ``services`` keys the infra inventory sets for the role.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        template = root / infra_inventory.INVENTORY_TEMPLATE
        template.parent.mkdir(parents=True)
        template.write_text(
            read_text(str(PROJECT_ROOT / infra_inventory.INVENTORY_TEMPLATE)),
            encoding="utf-8",
        )
        rendered = load_yaml(infra_inventory.render_inventory(root, env))
    return rendered["applications"][render.APPLICATION_ID]["services"]


def _infra_env() -> dict[str, str]:
    env = {key: f"/c/{name}" for name, key in infra_inventory.INVENTORY_KEYS.items()}
    env[FRONTEND_CONF_KEY] = PINNED_MAP
    env[infra_inventory.REGISTRIES_KEY] = "ghcr.io"
    return env


def _compose_services(override=None) -> dict:
    return load_yaml_str(render.compose(override))["services"]


def _conditions(task: dict) -> list:
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _flat_tasks() -> list[dict]:
    """Returns:
    The role tasks in run order, each block replaced by its children, every
    child guarded by the block's conditions before its own.
    """
    flat: list[dict] = []
    for task in load_yaml_any(str(TASKS)):
        if "block" not in task:
            flat.append(task)
            continue
        flat.extend(
            {**child, "when": _conditions(task) + _conditions(child)}
            for child in task["block"]
        )
    return flat


def _is_repository_task(task: dict) -> bool:
    return "bootstrap.sh" in task.get("ansible.builtin.shell", {}).get("cmd", "")


def _is_sidecar_wait(task: dict) -> bool:
    return task.get(COMMAND_MODULE, {}).get("argv", [])[:2] == WAIT_ARGV


def _is_compose_flush(task: dict) -> bool:
    return (
        task.get("include_role", {}).get("name") == "sys-svc-compose"
        and task.get("vars", {}).get("compose_handlers_flush") is True
    )


def _repositories_task_runs(override=None) -> bool:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        Whether the role task that writes the proxy repositories runs.
    """
    built = render.environment(override)
    [task] = [task for task in _flat_tasks() if _is_repository_task(task)]
    enabled = render.role_var(built, "CACHE_PACKAGE_BOOTSTRAP_ENABLED")
    return all(
        built.compile_expression(condition)(CACHE_PACKAGE_BOOTSTRAP_ENABLED=enabled)
        for condition in task["when"]
    )


def _compose_up_index() -> int:
    return next(
        index
        for index, task in enumerate(load_yaml_any(str(TASKS)))
        if _is_compose_flush(task)
    )


def _waits_for_the_sidecar(tasks: list[dict]) -> bool:
    """Args:
        tasks: a role task list.

    Returns:
        Whether a task waits for a container after the compose up flush has
        started the sidecar and before the repository task runs the bootstrap.
    """
    flush = next(index for index, task in enumerate(tasks) if _is_compose_flush(task))
    [repositories] = [
        index for index, task in enumerate(tasks) if _is_repository_task(task)
    ]
    return any(
        flush < index < repositories
        for index, task in enumerate(tasks)
        if _is_sidecar_wait(task)
    )


def _sidecar_wait() -> dict:
    [task] = [task for task in _flat_tasks() if _is_sidecar_wait(task)]
    return task


def _wait_runs(override=None, swarm: bool = False) -> bool:
    """Args:
        override: the ``services`` keys an inventory sets for the role.
        swarm: the IS_SWARM_MODE the deploy runs under.

    Returns:
        Whether the deploy waits for the bootstrap sidecar.
    """
    built = render.environment(override)
    values = {
        "CACHE_PACKAGE_BOOTSTRAP_ENABLED": render.role_var(
            built, "CACHE_PACKAGE_BOOTSTRAP_ENABLED"
        ),
        "IS_SWARM_MODE": swarm,
    }
    return all(
        built.compile_expression(condition)(**values)
        for condition in _sidecar_wait()["when"]
    )


def _wait_fails(rc: int, stdout: str, stderr: str) -> bool:
    """Args:
        rc: the exit code of ``container wait``.
        stdout: what it printed, the sidecar's exit code.
        stderr: its error output.

    Returns:
        Whether the deploy fails on that result.
    """
    task = _sidecar_wait()
    result = {task["register"]: {"rc": rc, "stdout": stdout, "stderr": stderr}}
    built = render.environment()
    return all(
        built.compile_expression(condition)(**result)
        for condition in task["failed_when"]
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


class TestFrontendMap(unittest.TestCase):
    def test_the_frontend_mounts_the_configured_map(self) -> None:
        self.assertEqual(_mounted_map(INFRA), PINNED_MAP)

    def test_the_infra_runner_hands_the_frontend_the_pinned_map(self) -> None:
        self.assertEqual(_mounted_map(_infra_services(_infra_env())), PINNED_MAP)

    def test_without_the_key_the_frontend_mounts_the_map_the_role_renders(
        self,
    ) -> None:
        rendered = render.role_var(
            render.environment(), "CACHE_PACKAGE_FRONTEND_CONF_HOST"
        )
        self.assertEqual(_mounted_map(), rendered)
        self.assertNotEqual(_mounted_map(), PINNED_MAP)


class TestRepositoriesUnderTheInfraRunner(unittest.TestCase):
    def test_the_infra_runner_starts_no_bootstrap_sidecar(self) -> None:
        self.assertNotIn("bootstrap", _compose_services(_infra_services(_infra_env())))

    def test_the_infra_runner_skips_the_role_repository_task(self) -> None:
        self.assertFalse(_repositories_task_runs(_infra_services(_infra_env())))

    def test_without_the_key_the_role_provisions_its_repositories(self) -> None:
        self.assertIn("bootstrap", _compose_services())
        self.assertTrue(_repositories_task_runs())


class TestOneBootstrapAtATime(unittest.TestCase):
    def test_the_deploy_waits_for_the_sidecar_before_its_own_bootstrap(self) -> None:
        self.assertTrue(_waits_for_the_sidecar(_flat_tasks()))

    def test_a_deploy_without_the_wait_is_caught(self) -> None:
        unguarded = [task for task in _flat_tasks() if not _is_sidecar_wait(task)]
        self.assertFalse(_waits_for_the_sidecar(unguarded))

    def test_a_wait_after_the_deploy_bootstrap_is_caught(self) -> None:
        late = [task for task in _flat_tasks() if not _is_sidecar_wait(task)]
        late.append(_sidecar_wait())
        self.assertFalse(_waits_for_the_sidecar(late))

    def test_it_waits_for_the_container_the_stack_names(self) -> None:
        built = render.environment()
        waited = built.from_string(_sidecar_wait()[COMMAND_MODULE]["argv"][2]).render(
            CACHE_PACKAGE_BOOTSTRAP_CONTAINER=render.role_var(
                built, "CACHE_PACKAGE_BOOTSTRAP_CONTAINER"
            )
        )
        self.assertEqual(
            _compose_services()["bootstrap"]["compose_only"][0],
            ["container_name", waited],
        )

    def test_it_waits_exactly_where_the_stack_runs_the_sidecar(self) -> None:
        self.assertTrue(_wait_runs())
        self.assertFalse(_wait_runs(swarm=True))
        self.assertFalse(_wait_runs(_infra_services(_infra_env())))

    def test_an_absent_or_failed_sidecar_leaves_the_verdict_to_the_deploy_bootstrap(
        self,
    ) -> None:
        self.assertFalse(_wait_fails(0, "0", ""))
        self.assertFalse(_wait_fails(0, "1", ""))
        self.assertFalse(_wait_fails(1, "", NO_SUCH))

    def test_a_wait_the_daemon_cannot_answer_fails_the_deploy(self) -> None:
        self.assertTrue(_wait_fails(1, "", DAEMON_DOWN))


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
