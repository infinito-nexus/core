"""Contract of the docker data-root filesystem resolver.

``resolve.sh`` hands its decision over a file in the ``GITHUB_ENV`` format, and
the per-distro caller passes it positionally to ``docker_dataroot.sh``. A key
renamed on either side is silent: the applying script receives an empty string,
reports "no filesystem stated", exits 0, and the run goes green with the feature
switched off. Checked here by executing the resolver: the keys it emits are the
keys its consumers read, naming kinds narrows the draw to them, the run's own
ENFORCED flag rather than the width of that list decides whether the pick is
binding, and a pick always comes out of the pool that was reported.

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

PICK = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "utils" / "filesystem" / "pick.sh"
)
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
POOL = re.compile(r"out of '([^']*)'")
ALL_DISTROS = ("arch", "debian", "ubuntu", "fedora", "centos")
KINDS = ("ext4", "btrfs", "zfs")


class Resolved:
    def __init__(self, stdout: str, stderr: str, env: str):
        self.stdout = stdout
        self.stderr = stderr
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


def resolve(
    stated: str,
    distros: str,
    scope: str,
    enforced: str = "false",
    pick: str = "",
) -> Resolved:
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "env"
        summary = Path(tmp) / "summary.md"
        env_file.touch()
        summary.touch()
        env = dict(os.environ)
        env.update(GITHUB_ENV=str(env_file), GITHUB_STEP_SUMMARY=str(summary))
        proc = subprocess.run(
            ["bash", str(RESOLVE), stated, "unit/test", distros, scope, enforced, pick],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return Resolved(proc.stdout, proc.stderr, read_text(str(env_file)))


class TestFilesystemResolve(unittest.TestCase):
    def test_the_emitted_keys_are_the_keys_its_consumers_read(self) -> None:
        consumed = set()
        for consumer in CONSUMERS:
            consumed |= set(CONSUMED.findall(read_text(str(consumer))))
        self.assertEqual(consumed, set(resolve("", "debian", "runner").env))

    def test_the_enforced_flag_decides_whether_the_pick_is_binding(self) -> None:
        """Not the width of the allow-list: the matrix narrows every ordinary
        row to one kind, and that must not read as a demand."""
        served = next((k for k in KINDS if kernel_serves(k)), None)
        if served is None:
            self.skipTest("this kernel serves nothing")
        self.assertEqual(
            resolve("", "debian", "runner", "true", served).required, "true"
        )
        self.assertEqual(
            resolve("", "debian", "runner", "false", served).required, "false"
        )
        self.assertEqual(resolve("", "debian", "runner").required, "false")

    def test_a_run_whose_whole_pool_is_unservable_fails_rather_than_leaving_it(
        self,
    ) -> None:
        """Falling back outside what the run permitted would be the silent
        substitution the flag exists to prevent."""
        unserved = next((k for k in KINDS if not kernel_serves(k)), None)
        if unserved is None:
            self.skipTest("this kernel serves every kind")
        self.assertEqual(
            resolve(unserved, "debian", "runner", "false", unserved).required, "true"
        )

    def test_an_enforced_kind_is_kept_even_when_the_kernel_cannot_serve_it(
        self,
    ) -> None:
        """The applying step is what fails; substituting a kind here would make
        the run green on something the operator did not ask for."""
        named = resolve("zfs", " ".join(ALL_DISTROS), "runner", "true", "zfs")
        self.assertEqual(named.picked, "zfs")
        self.assertEqual(named.required, "true")

    def test_an_unenforced_pick_the_kernel_cannot_serve_falls_back_out_loud(
        self,
    ) -> None:
        unserved = next((k for k in KINDS if not kernel_serves(k)), None)
        if unserved is None:
            self.skipTest("this kernel serves every kind, so nothing falls back")
        fell = resolve("", " ".join(ALL_DISTROS), "runner", "false", unserved)
        self.assertNotEqual(fell.picked, unserved)
        self.assertEqual(fell.required, "false")
        self.assertIn("does not serve", fell.stdout + fell.stderr)

    def test_a_fallback_stays_inside_what_the_run_permitted(self) -> None:
        """A run that allowed two kinds gets the other one, not a red row and
        not a third kind it never named."""
        unserved = next((k for k in KINDS if not kernel_serves(k)), None)
        served = next((k for k in KINDS if kernel_serves(k)), None)
        if unserved is None or served is None:
            self.skipTest("needs one served and one unserved kind on this host")
        fell = resolve(f"{served} {unserved}", "debian", "runner", "false", unserved)
        self.assertEqual(fell.picked, served)

    def test_a_pick_the_kernel_serves_is_taken_as_assigned(self) -> None:
        served = next((k for k in KINDS if kernel_serves(k)), None)
        if served is None:
            self.skipTest("this kernel serves nothing")
        self.assertEqual(
            resolve("", "debian", "runner", "false", served).picked, served
        )

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


class TestFilesystemPickJoint(unittest.TestCase):
    """The joint between pick.sh and resolve.sh, which is positional.

    An argument dropped there is silent: resolve.sh defaults it and the run
    goes on with the pick unenforced. Exercised end to end rather than by
    comparing the two argument lists, because only a run proves the order.
    """

    def _pick(self, **overrides: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env.pop("ACT", None)
            env.update(
                GITHUB_ACTIONS="1",
                GITHUB_ENV=str(Path(tmp) / "unused"),
                GITHUB_STEP_SUMMARY=str(Path(tmp) / "summary.md"),
                INFINITO_DISTRO="debian",
                **overrides,
            )
            proc = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        f'. "{PICK}"; filesystem_pick unit/test node; '
                        'printf "%s\\n%s\\n" '
                        '"${INFINITO_DOCKER_FILESYSTEM}" '
                        '"${INFINITO_DOCKER_FILESYSTEM_REQUIRED}"'
                    ),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        picked, required = proc.stdout.strip().splitlines()[-2:]
        return {"picked": picked, "required": required}

    def test_the_enforced_flag_reaches_the_resolver(self) -> None:
        served = next((k for k in KINDS if kernel_serves(k)), None)
        if served is None:
            self.skipTest("this kernel serves nothing")
        self.assertEqual(
            self._pick(
                INFINITO_DOCKER_FILESYSTEM_ALLOWED="",
                INFINITO_DOCKER_FILESYSTEM_PICK=served,
                INFINITO_DOCKER_FILESYSTEM_ENFORCED="true",
            )["required"],
            "true",
        )

    def test_the_row_pick_reaches_the_resolver(self) -> None:
        served = next((k for k in KINDS if kernel_serves(k)), None)
        if served is None:
            self.skipTest("this kernel serves nothing")
        self.assertEqual(
            self._pick(
                INFINITO_DOCKER_FILESYSTEM_ALLOWED="",
                INFINITO_DOCKER_FILESYSTEM_PICK=served,
                INFINITO_DOCKER_FILESYSTEM_ENFORCED="false",
            )["picked"],
            served,
        )
