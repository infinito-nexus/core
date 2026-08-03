"""Contract of the docker data-root filesystem resolver.

``resolve.sh`` hands its decision to the next workflow step through
``GITHUB_ENV``, and that step passes it positionally to ``docker_dataroot.sh``.
A key renamed on either side is silent: the applying script receives an empty
string, reports "no filesystem stated", exits 0, and the run goes green with the
feature switched off. Checked here by executing the resolver: the keys it emits
are the keys the workflows read, a stated pick is marked required while a drawn
one is not, a stated pick overrides the pool, and a pick is always drawn from a
pool the target can serve.

The pool contents are policy, not contract, and are deliberately not asserted -
the per-distro expectation is derived from the resolver's own answers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

RESOLVE = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "utils"
    / "filesystem"
    / "resolve.sh"
)
WORKFLOWS = [
    PROJECT_ROOT / ".github" / "workflows" / f"test-deploy-{mode}.yml"
    for mode in ("compose", "host", "swarm")
]
CONSUMED = re.compile(r"\$\{(INFINITO_DOCKER_FILESYSTEM[A-Z_]*)\}")
POOL = re.compile(r"random out of '([^']*)'")
ALL_DISTROS = ("arch", "debian", "ubuntu", "fedora", "centos")


class Resolved:
    def __init__(self, stdout: str, env: str):
        self.stdout = stdout
        self.env = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
        key = "INFINITO_DOCKER_FILESYSTEM"  # nocheck: resolve.sh writes it per matrix entry into GITHUB_ENV
        self.picked = self.env[key]
        self.required = self.env[f"{key}_REQUIRED"]
        match = POOL.search(stdout)
        self.pool = match.group(1).split() if match else None


def kernel_serves(kind: str) -> bool:
    """What the running kernel can mount, derived without asking resolve.sh."""
    if kind == "zfs":
        if Path("/dev/zfs").is_char_device():
            return True
    elif re.search(rf"^\s*{kind}$", read_text("/proc/filesystems"), re.MULTILINE):
        return True
    if shutil.which("modinfo") is None:
        return False
    return (
        subprocess.run(
            ["modinfo", kind], capture_output=True, text=True, check=False
        ).returncode
        == 0
    )


def resolve(stated: str, distros: str, scope: str) -> Resolved:
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "env"
        summary = Path(tmp) / "summary.md"
        env_file.touch()
        summary.touch()
        env = dict(os.environ)
        env.update(GITHUB_ENV=str(env_file), GITHUB_STEP_SUMMARY=str(summary))
        proc = subprocess.run(
            ["bash", str(RESOLVE), stated, "unit/test", distros, scope],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return Resolved(proc.stdout, read_text(str(env_file)))


class TestFilesystemResolve(unittest.TestCase):
    def test_the_emitted_keys_are_the_keys_the_workflows_read(self) -> None:
        consumed = set()
        for workflow in WORKFLOWS:
            consumed |= set(CONSUMED.findall(read_text(str(workflow))))
        self.assertEqual(consumed, set(resolve("", "debian", "runner").env))

    def test_a_stated_pick_is_required_and_a_drawn_one_is_not(self) -> None:
        self.assertEqual(resolve("zfs", "debian", "runner").required, "true")
        self.assertEqual(resolve("", "debian", "runner").required, "false")

    def test_a_stated_pick_overrides_the_pool(self) -> None:
        stated = resolve("zfs", " ".join(ALL_DISTROS), "runner")
        self.assertEqual(stated.picked, "zfs")
        self.assertIsNone(stated.pool)

    def test_a_drawn_pick_comes_from_the_reported_pool(self) -> None:
        for scope in ("runner", "node"):
            drawn = resolve("", " ".join(ALL_DISTROS), scope)
            self.assertIn(drawn.picked, drawn.pool)

    def test_the_runner_pool_is_exactly_what_this_kernel_serves(self) -> None:
        expected = [kind for kind in ("ext4", "btrfs", "zfs") if kernel_serves(kind)]
        self.assertEqual(resolve("", " ".join(ALL_DISTROS), "runner").pool, expected)

    def test_a_kernel_that_cannot_serve_it_keeps_it_out_of_every_scope(self) -> None:
        absent = [kind for kind in ("ext4", "btrfs", "zfs") if not kernel_serves(kind)]
        if not absent:
            self.skipTest("this kernel serves all three, nothing to exclude")
        for scope in ("runner", "node"):
            pool = resolve("", " ".join(ALL_DISTROS), scope).pool
            self.assertTrue(set(absent).isdisjoint(pool))

    def test_the_node_pool_also_drops_what_a_distro_cannot_install(self) -> None:
        runner = set(resolve("", " ".join(ALL_DISTROS), "runner").pool)
        node = set(resolve("", " ".join(ALL_DISTROS), "node").pool)
        self.assertTrue(node.issubset(runner))

    def test_a_missing_scope_is_a_hard_error(self) -> None:
        proc = subprocess.run(
            ["bash", str(RESOLVE), "", "unit/test", "debian"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
