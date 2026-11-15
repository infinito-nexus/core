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


def _mount(entry: str | dict) -> tuple[str, str]:
    """Return the source and target of a volume entry.

    Args:
        entry: a short- or long-syntax compose volume entry.

    Returns:
        The source, empty for an anonymous volume, and the target.
    """
    if isinstance(entry, dict):
        return entry.get("source", ""), entry["target"]
    parts = _short(entry)
    return ("", parts[0]) if len(parts) == 1 else (parts[0], parts[1])


def _compose_files() -> list[dict]:
    paths = [
        PROJECT_ROOT / "compose.yml",
        *sorted(PROJECT_ROOT.glob("compose/**/*.yml")),
    ]
    docs = [load_yaml_any(str(path)) for path in paths]
    return [doc for doc in docs if isinstance(doc, dict) and "services" in doc]


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
            read_text(str(PROJECT_ROOT / "compose" / "infra-consumer.override.yml")),
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


class TestSharedCacheLeavesOtherCachesAlone(unittest.TestCase):
    def test_the_overrides_add_only_the_shared_folder_the_script_and_pip_npm(
        self,
    ) -> None:
        for parts, environment in (
            (
                ("compose", "shared-cache.override.yml"),
                ["PIP_CACHE_DIR", "npm_config_cache"],
            ),
            (("compose", "swarm", "shared-cache.override.yml"), []),
        ):
            for name, service in _load(*parts)["services"].items():
                with self.subTest(file="/".join(parts), service=name):
                    targets = [_mount(v)[1] for v in service["volumes"]]
                    self.assertEqual(
                        sorted(_var(t) or t for t in targets),
                        sorted([SHARED, PACMAN_SCRIPT]),
                    )
                    self.assertEqual(
                        sorted(service.get("environment", {})), environment
                    )


class TestNoSharedDockerDataRoot(unittest.TestCase):
    def test_no_two_services_and_no_shared_cache_back_one_docker_data_root(
        self,
    ) -> None:
        owners: dict[str, set[str]] = {}
        for doc in _compose_files():
            for name, service in doc["services"].items():
                for entry in (service or {}).get("volumes", []):
                    source, target = _mount(entry)
                    if source and (
                        target == "/var/lib/docker"
                        or _var(target) == "INFINITO_DOCKER_MOUNT"
                    ):
                        owners.setdefault(source, set()).add(name)
        self.assertTrue(owners)
        self.assertEqual({s: n for s, n in owners.items() if len(n) > 1}, {})
        self.assertEqual([s for s in owners if SHARED in s or HOST_PACMAN in s], [])


if __name__ == "__main__":
    unittest.main()
