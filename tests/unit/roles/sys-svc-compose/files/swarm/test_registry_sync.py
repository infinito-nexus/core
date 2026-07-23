import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from utils.cache.yaml import dump_yaml

from . import PROJECT_ROOT

PREFIX = "registry.example:5000/"


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestSwarmRegistrySync(unittest.TestCase):
    def setUp(self) -> None:
        self.m = _load_module(
            "roles/sys-svc-compose/files/swarm/registry_sync.py",
            "swarm_registry_sync_mod",
        )

    def _sync(
        self, services: dict, *, prefix: str = PREFIX, manifest=lambda img: False
    ):
        """Run sync() against a temp compose with docker mocked out; return the
        list of docker argv lists the script issued."""
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], timeout: int = 600) -> int:
            calls.append(cmd)
            return 0

        with tempfile.TemporaryDirectory() as td:
            cf = Path(td) / "compose.yml"
            dump_yaml(cf, {"services": services})
            with (
                patch.object(self.m, "run", side_effect=fake_run),
                patch.object(self.m, "manifest_exists", side_effect=manifest),
            ):
                rc = self.m.sync(compose_file=cf, prefix=prefix)
        self.assertEqual(rc, 0)
        return calls

    def test_sibling_of_local_build_is_not_pulled(self) -> None:
        """daemon/websocket reference espocrm's already-prefixed build image
        without their own build:; that local-only ref must NOT be pulled from
        the registry (the espocrm_custom 'pull access denied' regression), and
        locally-built images must never be rmi'd (recovery/base images depend on
        them staying in the engine store)."""
        img = f"{PREFIX}espocrm_custom:latest"
        calls = self._sync(
            {
                "espocrm": {"build": {"context": "."}, "image": img},
                "daemon": {"image": img},
                "websocket": {"image": img},
            }
        )
        self.assertNotIn(["docker", "pull", "espocrm_custom:latest"], calls)
        self.assertIn(["docker", "push", img], calls)
        rmi = [c for c in calls if c[:2] == ["docker", "rmi"]]
        self.assertEqual(rmi, [])

    def test_pulled_external_is_removed_after_push(self) -> None:
        """A mirrored external is dropped from the engine store after the push so
        it is not double-stored (engine + registry) on constrained runners."""
        calls = self._sync({"web": {"image": f"{PREFIX}nginx:1.25"}})
        self.assertIn(["docker", "rmi", f"{PREFIX}nginx:1.25", "nginx:1.25"], calls)

    def test_shared_external_removed_once(self) -> None:
        """Two services referencing the same external yield a single rmi pair."""
        calls = self._sync(
            {
                "a": {"image": "nginx:1.25"},
                "b": {"image": "nginx:1.25"},
            }
        )
        rmi = [c for c in calls if c[:2] == ["docker", "rmi"]]
        self.assertEqual(rmi, [["docker", "rmi", f"{PREFIX}nginx:1.25", "nginx:1.25"]])

    def test_real_upstream_image_is_still_pulled(self) -> None:
        """A prefixed image with a genuine upstream (not locally built) must
        still be pulled + retagged; the de-prefix must not over-skip."""
        calls = self._sync({"web": {"image": f"{PREFIX}nginx:1.25"}})
        self.assertIn(["docker", "pull", "nginx:1.25"], calls)
        self.assertIn(["docker", "tag", "nginx:1.25", f"{PREFIX}nginx:1.25"], calls)

    def test_already_in_registry_is_not_repulled(self) -> None:
        """If the prefixed image already has a manifest in the registry, it is
        neither pulled nor re-pushed."""
        img = f"{PREFIX}nginx:1.25"
        calls = self._sync({"web": {"image": img}}, manifest=lambda i: True)
        self.assertNotIn(["docker", "pull", "nginx:1.25"], calls)
        self.assertNotIn(["docker", "push", img], calls)

    def test_main_empty_prefix_short_circuits(self) -> None:
        """Compose mode passes an empty --registry-prefix; main() returns early
        and never touches docker."""
        import sys

        argv = ["swarm_registry_sync.py", "--chdir", "/x", "--registry-prefix", ""]
        with (
            patch.object(sys, "argv", argv),
            patch.object(self.m, "run") as run_mock,
        ):
            rc = self.m.main()
        self.assertEqual(rc, 0)
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
