"""The lab node play layers pacman over the shared cache before the first package install."""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

PLAYBOOK = PROJECT_ROOT / "compose" / "swarm" / "playbook.yml"
PACMAN_SCRIPT = "/usr/local/bin/pacman-cache.sh"
FIRST_INSTALL = "scripts/tests/deploy/utils/filesystem/docker_dataroot.sh"


class TestNodePacmanLayering(unittest.TestCase):
    def setUp(self) -> None:
        (self.play,) = load_yaml_any(str(PLAYBOOK))
        self.tasks = self.play["tasks"]

    def _index(self, matches) -> int:
        found = [i for i, task in enumerate(self.tasks) if matches(task)]
        self.assertEqual(len(found), 1, found)
        return found[0]

    def _probe(self) -> int:
        return self._index(
            lambda task: task.get("stat", {}).get("path") == PACMAN_SCRIPT
        )

    def _layer(self) -> int:
        return self._index(
            lambda task: (
                isinstance(task.get("command"), dict)
                and task["command"].get("argv", [None])[0] == PACMAN_SCRIPT
            )
        )

    def test_the_cache_paths_come_from_the_run_environment(self) -> None:
        self.assertEqual(
            [
                self.play["vars"]["lab_shared_cache"],
                self.play["vars"]["lab_host_pacman_cache"],
            ],
            [
                "{{ lookup('env', 'INFINITO_CACHE_SHARED_HOST_PATH') }}",
                "{{ lookup('env', 'INFINITO_CACHE_HOST_PACMAN_PATH') }}",
            ],
        )

    def test_the_script_layers_the_node_pacman_conf_over_both_caches(self) -> None:
        self.assertEqual(
            self.tasks[self._layer()]["command"]["argv"],
            [
                PACMAN_SCRIPT,
                "/etc/pacman.conf",
                "{{ lab_shared_cache }}",
                "{{ lab_host_pacman_cache }}",
            ],
        )

    def test_only_a_node_that_mounts_the_script_runs_it(self) -> None:
        probe = self.tasks[self._probe()]
        self.assertEqual(
            self.tasks[self._layer()]["when"],
            f"{probe['register']}.stat.exists",
        )
        self.assertLess(self._probe(), self._layer())

    def test_the_layering_runs_before_the_first_package_install(self) -> None:
        install = self._index(lambda task: FIRST_INSTALL in str(task.get("script")))
        self.assertLess(self._layer(), install)


if __name__ == "__main__":
    unittest.main()
