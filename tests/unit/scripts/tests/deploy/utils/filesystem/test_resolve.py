"""Contract of the docker data-root filesystem resolver.

``resolve.sh`` hands its decision over a file in the ``GITHUB_ENV`` format, and
the per-distro caller passes it positionally to ``docker_dataroot.sh``. A key
renamed on either side is silent: the applying script receives an empty string,
reports "no filesystem stated", exits 0, and the run goes green with the feature
switched off. Checked here by executing the resolver: the keys it emits are the
keys its consumers read, naming kinds narrows the draw to them and marks it
required while an empty allow-list does not, and a pick always comes out of the
pool that was reported.

The pool contents are policy, not contract, and are deliberately not asserted -
the expectation is derived from the resolver's own answers. What is asserted is
that the pool depends on neither the distro set nor the scope, because every
distro image carries all three userlands.
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
CONSUMERS = [
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "ci" / "one.sh",
    PROJECT_ROOT / "compose" / "swarm" / "playbook.yml",
]
CONSUMED = re.compile(r"INFINITO_DOCKER_FILESYSTEM(?:_REQUIRED)?\b")
POOL = re.compile(r"random out of '([^']*)'")
ALL_DISTROS = ("arch", "debian", "ubuntu", "fedora", "centos")


class Resolved:
    def __init__(self, stdout: str, env: str):
        self.stdout = stdout
        self.env = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
        key = "INFINITO_DOCKER_FILESYSTEM"  # nocheck: resolve.sh writes it per distro iteration in the GITHUB_ENV format
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
    def test_the_emitted_keys_are_the_keys_its_consumers_read(self) -> None:
        consumed = set()
        for consumer in CONSUMERS:
            consumed |= set(CONSUMED.findall(read_text(str(consumer))))
        self.assertEqual(consumed, set(resolve("", "debian", "runner").env))

    def test_naming_kinds_makes_the_pick_required_and_an_empty_list_does_not(
        self,
    ) -> None:
        self.assertEqual(resolve("zfs", "debian", "runner").required, "true")
        self.assertEqual(resolve("", "debian", "runner").required, "false")

    def test_naming_one_kind_pins_the_pick_to_it(self) -> None:
        named = resolve("zfs", " ".join(ALL_DISTROS), "runner")
        self.assertEqual(named.picked, "zfs")
        self.assertEqual(named.pool, ["zfs"])

    def test_naming_several_kinds_keeps_the_draw_inside_them(self) -> None:
        named = resolve("ext4 btrfs", " ".join(ALL_DISTROS), "runner")
        self.assertTrue(set(named.pool).issubset({"ext4", "btrfs"}))
        self.assertIn(named.picked, named.pool)

    def test_a_kind_the_project_does_not_know_is_a_hard_error(self) -> None:
        proc = subprocess.run(
            ["bash", str(RESOLVE), "reiserfs", "unit/test", "debian", "runner"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("reiserfs", proc.stderr)

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

    def test_the_distro_set_does_not_narrow_the_pool(self) -> None:
        every = resolve("", " ".join(ALL_DISTROS), "node").pool
        for distro in ALL_DISTROS:
            self.assertEqual(resolve("", distro, "node").pool, every)

    def test_both_scopes_draw_from_the_same_pool(self) -> None:
        runner = resolve("", " ".join(ALL_DISTROS), "runner").pool
        node = resolve("", " ".join(ALL_DISTROS), "node").pool
        self.assertEqual(node, runner)

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
