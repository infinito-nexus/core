"""01_bootstrap.sh layers the shared cache overrides onto the lab nodes only when their variables are set."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

BOOTSTRAP = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "swarm"
    / "routine"
    / "01_bootstrap.sh"
)
SHARED = "INFINITO_CACHE_SHARED_HOST_PATH"
HOST_PACMAN = "INFINITO_CACHE_HOST_PACMAN_PATH"
BASE = "compose/swarm/compose.yml"
CACHE = "compose/swarm/cache.override.yml"
SHARED_CACHE = "compose/swarm/shared-cache.override.yml"
PACMAN = "compose/swarm/pacman.override.yml"
DOCKER_STUB = """#!/usr/bin/env bash
printf 'docker %s\\n' "$*" >>"${STUB_LOG}"
if [ "$1" = network ] && [ "$2" = inspect ]; then
	echo 10.47.0.0/24
fi
exit 0
"""
NOOP_STUB = "#!/usr/bin/env bash\nexit 0\n"
PYTHON_STUB = """#!/usr/bin/env bash
if [ "$*" = "-m cli.administration.infra attach" ] && [ "${STUB_FRONTEND}" = up ]; then
	echo infinito-infra
fi
exit 0
"""
TOPOLOGY_STUB = (
    "SWARM_NAME=demo\n"
    "MGR=demo-mgr\n"
    "WRK1=demo-wrk1\n"
    "WRK2=demo-wrk2\n"
    "NFS_SERVER=demo-nfs\n"
    "BACKUP_NODE=demo-backup\n"
    "PROXMOX_NODE=demo-pve\n"
)


def bootstrap(frontend: bool, cache_env: dict[str, str]) -> dict[str, list[str]]:
    """Run 01_bootstrap.sh against stubs and return the compose files per call.

    Args:
        frontend: whether a package-cache frontend runs on the host.
        cache_env: the shared cache keys the run exports; a key left out is
            missing from the environment.

    Returns:
        The ``-f`` files of the ``build`` and the ``up`` compose call, relative
        to the checkout.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        swarm = root / "scripts" / "tests" / "deploy" / "swarm"
        (swarm / "routine").mkdir(parents=True)
        (swarm / "routine" / "01_bootstrap.sh").symlink_to(BOOTSTRAP)
        bin_dir = Path(tmp) / "bin"
        files = {
            swarm / "utils" / "topology" / "base.sh": TOPOLOGY_STUB,
            swarm / "utils" / "unmount" / "nfs_mounts.sh": NOOP_STUB,
            swarm / "utils" / "unmount" / "host_state.sh": NOOP_STUB,
            root / "scripts" / "meta" / "env" / "load.sh": "",
            bin_dir / "docker": DOCKER_STUB,
            bin_dir / "python3": PYTHON_STUB,
            **{
                bin_dir / name: NOOP_STUB
                for name in ("apt-get", "sudo", "ansible-playbook", "make")
            },
        }
        for path, body in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            path.chmod(0o755)
        log = Path(tmp) / "calls.log"
        log.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("INFINITO_") and k != "BASH_ENV"
        }
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_FRONTEND="up" if frontend else "down",
            RUNNER_TEMP=tmp,
            APP_ID="web-app-demo",
            INFINITO_DOMAIN="infinito.example",
            INFINITO_CONTAINER="own",
            INFINITO_DIR_VAR_LIB="/var/lib/infinito",
            INFINITO_IMAGE="infinito-arch:latest",
            INFINITO_INSTANCE="0",
            INFINITO_CACHE_REGISTRY_CA_HOST_PATH="/srv/registry-ca",
            **cache_env,
        )
        done = subprocess.run(
            ["bash", str(swarm / "routine" / "01_bootstrap.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise AssertionError(f"bootstrap failed: {done.stderr}")
        calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
        out: dict[str, list[str]] = {}
        for call in calls:
            words = call.split()
            if words[:2] != ["docker", "compose"]:
                continue
            step = "build" if "build" in words else "up"
            out[step] = [
                os.path.relpath(os.path.normpath(words[i + 1]), root)
                for i, word in enumerate(words)
                if word == "-f"
            ]
        return out


class TestSwarmSharedCacheLayering(unittest.TestCase):
    def test_a_shared_folder_is_layered_onto_the_nodes(self) -> None:
        calls = bootstrap(True, {SHARED: "/srv/shared", HOST_PACMAN: ""})
        self.assertEqual(calls["build"], [BASE, CACHE, SHARED_CACHE])

    def test_a_host_pacman_cache_adds_its_read_only_layer(self) -> None:
        calls = bootstrap(True, {SHARED: "/srv/shared", HOST_PACMAN: "/srv/pkg"})
        self.assertEqual(calls["build"], [BASE, CACHE, SHARED_CACHE, PACMAN])

    def test_a_host_pacman_cache_needs_the_shared_folder(self) -> None:
        calls = bootstrap(True, {SHARED: "", HOST_PACMAN: "/srv/pkg"})
        self.assertEqual(calls["build"], [BASE, CACHE])

    def test_an_env_without_the_cache_keys_layers_neither(self) -> None:
        calls = bootstrap(True, {})
        self.assertEqual(calls["build"], [BASE, CACHE])

    def test_without_a_cache_stack_no_cache_override_is_layered(self) -> None:
        calls = bootstrap(False, {SHARED: "/srv/shared", HOST_PACMAN: "/srv/pkg"})
        self.assertEqual(calls["build"], [BASE])

    def test_the_nodes_start_with_the_files_they_were_built_with(self) -> None:
        calls = bootstrap(True, {SHARED: "/srv/shared", HOST_PACMAN: "/srv/pkg"})
        self.assertEqual(calls["up"], calls["build"])


if __name__ == "__main__":
    unittest.main()
