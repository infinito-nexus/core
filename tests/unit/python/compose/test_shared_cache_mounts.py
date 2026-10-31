"""The cache overrides mount the shared folder at its host path; nothing always layered needs it."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.render import cache_consumer_yml
from utils.cache.yaml import load_yaml_any

SHARED = "INFINITO_CACHE_SHARED_HOST_PATH"
HOST_PACMAN = "INFINITO_CACHE_HOST_PACMAN_PATH"
PACMAN_SCRIPT = "/usr/local/bin/pacman-cache.sh"
LAB_NODES = (
    "nfs-server",
    "swarm-mgr-01",
    "swarm-wrk-01",
    "swarm-wrk-02",
    "backup-host",
)


def _var(text: str) -> str:
    """Return the variable a compose interpolation names, empty for a literal."""
    found = re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)(?::\?[^}]*)?\}", text.strip())
    return found.group(1) if found else ""


def _short(entry: str) -> list[str]:
    """Split a short-syntax mount on the colons outside interpolations."""
    parts, depth, current = [], 0, ""
    for char in entry:
        if char == "{" and current.endswith("$"):
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        if char == ":" and not depth:
            parts.append(current)
            current = ""
            continue
        current += char
    return [*parts, current]


def _load(*parts: str) -> dict:
    return load_yaml_any(str(PROJECT_ROOT.joinpath(*parts)))


class TestComposeSlot(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load("compose", "shared-cache.override.yml")["services"][
            "infinito"
        ]

    def test_the_shared_folder_is_bound_read_write_at_its_host_path(self) -> None:
        binds = [
            v
            for v in self.runner["volumes"]
            if isinstance(v, dict) and _var(v["source"]) == SHARED
        ]
        self.assertEqual(len(binds), 1, self.runner["volumes"])
        self.assertEqual(_var(binds[0]["target"]), SHARED)
        self.assertFalse(binds[0].get("read_only", False))

    def test_pip_and_npm_cache_below_the_shared_folder(self) -> None:
        env = self.runner["environment"]
        self.assertRegex(env["PIP_CACHE_DIR"], rf"^\$\{{{SHARED}[^}}]*\}}/pip$")
        self.assertRegex(env["npm_config_cache"], rf"^\$\{{{SHARED}[^}}]*\}}/npm$")

    def test_the_pacman_script_is_mounted(self) -> None:
        targets = [_short(v)[1] for v in self.runner["volumes"] if isinstance(v, str)]
        self.assertIn(PACMAN_SCRIPT, targets)


class TestAlwaysLayeredFiles(unittest.TestCase):
    def test_the_always_layered_files_never_name_the_cache_variables(self) -> None:
        always = (
            cache_consumer_yml(),
            read_text(str(PROJECT_ROOT / "compose.yml")),
            read_text(str(PROJECT_ROOT / "compose" / "cache.override.yml")),
            read_text(str(PROJECT_ROOT / "compose" / "swarm" / "cache.override.yml")),
        )
        for text in always:
            self.assertNotIn(SHARED, text)
            self.assertNotIn(HOST_PACMAN, text)


class TestHostPacmanOverride(unittest.TestCase):
    def test_the_host_pacman_cache_is_mounted_read_only_at_its_host_path(self) -> None:
        (bind,) = _load("compose", "pacman.override.yml")["services"]["infinito"][
            "volumes"
        ]
        self.assertEqual(_var(bind["source"]), HOST_PACMAN)
        self.assertEqual(_var(bind["target"]), HOST_PACMAN)
        self.assertTrue(bind["read_only"])


class TestSwarmLabNodes(unittest.TestCase):
    def test_every_node_binds_the_shared_folder_read_write(self) -> None:
        services = _load("compose", "swarm", "shared-cache.override.yml")["services"]
        for node in LAB_NODES:
            with self.subTest(node=node):
                mounts = [_short(v) for v in services[node]["volumes"]]
                shared = [m for m in mounts if _var(m[0]) == SHARED]
                self.assertEqual(len(shared), 1, mounts)
                self.assertEqual(_var(shared[0][1]), SHARED)
                self.assertEqual(len(shared[0]), 2, "read-write: no :ro suffix")
                self.assertIn(PACMAN_SCRIPT, [m[1] for m in mounts])

    def test_every_node_reads_the_host_pacman_cache_read_only(self) -> None:
        services = _load("compose", "swarm", "pacman.override.yml")["services"]
        for node in LAB_NODES:
            with self.subTest(node=node):
                (mount,) = [_short(v) for v in services[node]["volumes"]]
                self.assertEqual(
                    [_var(mount[0]), _var(mount[1]), mount[2]],
                    [HOST_PACMAN, HOST_PACMAN, "ro"],
                )


if __name__ == "__main__":
    unittest.main()
