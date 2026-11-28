from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
from utils.storage.constrained import store_consumers

if TYPE_CHECKING:
    from types import ModuleType

ROLE = PROJECT_ROOT / "roles" / "svc-ai-models"
GROUPS = {
    "svc-swarm-manager": ["manager"],
    "svc-swarm-node": ["manager", "worker-1", "worker-2"],
}
PLAY_HOSTS = GROUPS["svc-swarm-node"]
BODY = b"pinned model weights"
RECORD = {
    "name": "model",
    "url": "https://huggingface.co/org/repo/resolve/0123/model.gguf",
    "sha256": hashlib.sha256(BODY).hexdigest(),
    "bytes": len(BODY),
}
BARRIER_SECONDS = 30


SANDBOXED = {**GROUPS, "svc-virt-kata": ["manager", "worker-2"]}
UNPLACED_SEED_NODES = (
    "{{ ((groups['svc-swarm-manager'] | default([])) + (groups['svc-swarm-node']"
    " | default([]))) | unique | list if IS_SWARM_MODE else [inventory_hostname] }}"
)


def _seed_nodes(**context: object) -> list[str]:
    variables = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
    environment = NativeEnvironment()
    sandbox = environment.from_string(variables["MODELS_SANDBOX_NODES"]).render(
        **context
    )
    template = environment.from_string(variables["MODELS_SEED_NODES"])
    return template.render(MODELS_SANDBOX_NODES=sandbox, **context)


def _kata_enabled(role_dir: Path) -> bool:
    services = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    kata = services.get("kata") if isinstance(services, dict) else None
    return isinstance(kata, dict) and kata.get("enabled") is True


def _store_module() -> ModuleType:
    path = ROLE / "library" / "artefact_store.py"
    spec = importlib.util.spec_from_file_location("svc_ai_models_seed_store", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seeders(*, swarm: bool) -> list[str]:
    """
    Args:
        swarm: the value IS_SWARM_MODE renders to.

    Returns:
        The play hosts that run the seed task, each looping over every node.
    """
    [task] = load_yaml_any(str(ROLE / "tasks" / "utils" / "seed.yml"))
    environment = NativeEnvironment()
    environment.filters["bool"] = bool
    once = environment.from_string(str(task.get("run_once"))).render(
        IS_SWARM_MODE=swarm
    )
    return PLAY_HOSTS[:1] if once else PLAY_HOSTS


def _seed_one_node(writers: int) -> list[str]:
    """
    Args:
        writers: the seed runs that write the same node's store at once.

    Returns:
        The error of every run that failed.
    """
    store = _store_module()
    barrier = threading.Barrier(writers, timeout=BARRIER_SECONDS)

    def fetch(_url: str, dest: Path) -> None:
        dest.write_bytes(BODY)
        barrier.wait()

    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(writers) as pool:
        runs = [
            pool.submit(store.store, Path(tmp), [RECORD], fetch) for _ in range(writers)
        ]
        errors = [run.exception() for run in runs]
    return [str(error) for error in errors if error is not None]


class TestSeedNodes(unittest.TestCase):
    def test_a_swarm_seeds_every_manager_and_node_once(self) -> None:
        nodes = _seed_nodes(
            groups=GROUPS, IS_SWARM_MODE=True, inventory_hostname="manager"
        )
        self.assertEqual(nodes, ["manager", "worker-1", "worker-2"])

    def test_a_sandbox_worker_is_not_seeded(self) -> None:
        nodes = _seed_nodes(
            groups=SANDBOXED, IS_SWARM_MODE=True, inventory_hostname="manager"
        )
        self.assertEqual(nodes, ["manager", "worker-1"])

    def test_the_unplaced_seed_set_fills_the_sandbox_worker(self) -> None:
        nodes = (
            NativeEnvironment()
            .from_string(UNPLACED_SEED_NODES)
            .render(groups=SANDBOXED, IS_SWARM_MODE=True, inventory_hostname="manager")
        )
        self.assertIn("worker-2", nodes)

    def test_no_store_consumer_is_sandboxed(self) -> None:
        consumers = store_consumers(PROJECT_ROOT / "roles")
        self.assertTrue(consumers)
        sandboxed = sorted(
            role for role in consumers if _kata_enabled(PROJECT_ROOT / "roles" / role)
        )
        self.assertEqual(sandboxed, [])

    def test_compose_seeds_only_the_deploy_host(self) -> None:
        nodes = _seed_nodes(
            groups=GROUPS, IS_SWARM_MODE=False, inventory_hostname="host"
        )
        self.assertEqual(nodes, ["host"])

    def test_the_seed_and_the_refusal_run_on_every_seed_node(self) -> None:
        for name in ("seed.yml", "require.yml"):
            with self.subTest(file=name):
                [task] = load_yaml_any(str(ROLE / "tasks" / "utils" / name))
                self.assertEqual(
                    (task["loop"], task["delegate_to"]),
                    ("{{ MODELS_SEED_NODES }}", "{{ models_node }}"),
                )


class TestOneWriterPerNodeStore(unittest.TestCase):
    def test_a_swarm_node_store_is_seeded_by_one_play_host(self) -> None:
        self.assertEqual(_seed_one_node(len(_seeders(swarm=True))), [])

    def test_compose_seeds_each_host_into_its_own_store(self) -> None:
        self.assertEqual(_seeders(swarm=False), PLAY_HOSTS)

    def test_every_play_host_seeding_one_node_breaks_its_store(self) -> None:
        self.assertEqual(len(_seed_one_node(len(PLAY_HOSTS))), len(PLAY_HOSTS) - 1)


class TestSeedInputsUnderAForeignInclude(unittest.TestCase):
    CALLER = "svc-ai-libretranslate-engine"

    def _render(self, key: str) -> tuple[object, list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []

        def lookup(kind: str, *terms: str) -> object:
            calls.append((kind, *terms))
            return {self.CALLER: {}} if kind == "applications_current_play" else ""

        variables = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
        template = NativeEnvironment().from_string(variables[key])
        return template.render(lookup=lookup, application_id=self.CALLER), calls

    def test_the_config_lookups_read_the_model_role_not_the_caller(self) -> None:
        for key in ("MODELS_ARTEFACT_BASE", "MODELS_FETCH_TIMEOUT"):
            with self.subTest(key=key):
                _, calls = self._render(key)
                self.assertEqual([call[:2] for call in calls], [("config", ROLE.name)])

    def test_the_deployed_roles_add_the_model_role_not_the_caller(self) -> None:
        roles, _ = self._render("MODELS_DEPLOYED_ROLES")
        self.assertEqual(roles, [self.CALLER, ROLE.name])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
