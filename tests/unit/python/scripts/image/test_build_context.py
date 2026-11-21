"""A local toolchain build sends the toolchain stage's inputs as its context and nothing else."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.docker.image.toolchain import DOCKERFILE, input_files

from ._checkout import loaded_env, loaded_in, stub_docker, toolchain_checkout

ONE_GIB = 1 << 30
STRAYS = (
    ".claude/worktrees/agent/big.bin",
    ".worktrees/sibling/big.bin",
    "untracked-dir/big.bin",
)


class TestBuildContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        stub_docker(cls.base)
        cls.checkout = toolchain_checkout(cls.base)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _build(self, *args: str) -> tuple[list[str], dict[str, int]]:
        env = loaded_in(self.checkout, loaded_env(self.base))
        log = Path(env["STUB_LOG"])
        context = Path(env["STUB_CONTEXT"])
        log.unlink(missing_ok=True)
        context.unlink(missing_ok=True)
        subprocess.run(
            ["bash", str(self.checkout / "scripts/image/build.sh"), *args],
            cwd=self.checkout,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        sizes = {}
        for line in context.read_text().splitlines():  # nocheck: cache-read  stub file
            path, size = line.rsplit(" ", 1)
            sizes[path] = int(size)
        return log.read_text().splitlines(), sizes  # nocheck: cache-read  stub call log

    def test_the_context_holds_exactly_the_input_set(self) -> None:
        calls, sizes = self._build("--tag", "primary/debian:probe")
        self.assertEqual(sorted(sizes), input_files(self.checkout))
        build = next(call for call in calls if call.startswith("build "))
        self.assertIn("--target toolchain", build)
        self.assertIn(f"--file {self.checkout / DOCKERFILE}", build)

    def test_big_files_outside_the_inputs_leave_the_context_unchanged(self) -> None:
        _, before = self._build("--tag", "primary/debian:probe")
        for rel in STRAYS:
            stray = self.checkout / rel
            stray.parent.mkdir(parents=True, exist_ok=True)
            with stray.open("wb") as handle:
                handle.truncate(ONE_GIB)
        try:
            _, after = self._build("--tag", "primary/debian:probe")
        finally:
            for rel in STRAYS:
                (self.checkout / rel).unlink()
        self.assertEqual(after, before)
        self.assertNotIn(ONE_GIB, after.values())

    def test_a_full_build_keeps_the_whole_tree_as_its_context(self) -> None:
        calls, _ = self._build("--tag", "primary/debian:probe", "--target", "full")
        build = next(call for call in calls if call.startswith("build "))
        self.assertTrue(build.endswith(" ."), build)
        self.assertIn("--target full", build)


if __name__ == "__main__":
    unittest.main()
