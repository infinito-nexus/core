"""``make build-cleanup`` keeps the toolchain images a registered worktree resolves or a container uses."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ._checkout import (
    DISTRO,
    PARENT_IMAGE,
    git,
    loaded_env,
    resolve_tag,
    stub_docker,
    toolchain_checkout,
)

DOTENV = (
    "INFINITO_CA_BUNDLE_CANDIDATES=\n"
    f"INFINITO_DISTRO={DISTRO}\n"
    "INFINITO_LINT_RUNNER=docker\n"
    f"INFINITO_PARENT_IMAGE={PARENT_IMAGE}\n"
    "INFINITO_SRC_DIR=/opt/src/infinito\n"
    "INFINITO_VENV_DIR=/opt/venvs/infinito\n"
)
ORPHAN = f"primary/{DISTRO}:0123456789abcdef"
OTHER_DISTRO = "primary/arch:fedcba9876543210"
IN_USE = f"primary/{DISTRO}:00000000000000ff"
NOT_TOOLCHAIN = (f"primary/{DISTRO}:latest", f"other/{DISTRO}:0123456789abcdef")


class TestCleanupKeep(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        stub_docker(cls.base)
        cls.primary = toolchain_checkout(cls.base)
        (cls.primary / ".env").write_text(DOTENV)
        cls.changed = cls.base / "changed-inputs"
        git(cls.primary, "worktree", "add", "--quiet", "--detach", str(cls.changed))
        venv = cls.changed / "scripts/install/venv.sh"
        text = venv.read_text()  # nocheck: cache-read  tempdir copy the test edits
        venv.write_text(text + "\n# probe\n")
        (cls.changed / ".env").write_text(DOTENV)
        resolving = loaded_env(cls.base, STUB_PARENT_ID="")
        cls.primary_tag = resolve_tag(cls.primary, resolving)
        cls.changed_tag = resolve_tag(cls.changed, resolving)
        images = [
            cls.primary_tag,
            cls.changed_tag,
            ORPHAN,
            OTHER_DISTRO,
            IN_USE,
            *NOT_TOOLCHAIN,
        ]
        env = loaded_env(
            cls.base,
            STUB_IMAGES="".join(f"{image}\n" for image in images),
            STUB_CONTAINER_IMAGES=f"{IN_USE}\ncoredns/coredns:1.14.4\n",
        )
        Path(env["STUB_LOG"]).unlink(missing_ok=True)
        cls.done = subprocess.run(
            ["bash", str(cls.primary / "scripts/image/cleanup_local.sh")],
            cwd=cls.primary,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        log = Path(env["STUB_LOG"]).read_text()  # nocheck: cache-read  stub call log
        cls.removed = {
            call.removeprefix("image rm ")
            for call in log.splitlines()
            if call.startswith("image rm ")
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_cleanup_succeeds(self) -> None:
        self.assertEqual(self.done.returncode, 0, self.done.stderr)

    def test_the_worktrees_differ_in_their_inputs(self) -> None:
        self.assertNotEqual(self.primary_tag, self.changed_tag)

    def test_images_registered_worktrees_resolve_stay(self) -> None:
        self.assertNotIn(self.primary_tag, self.removed)
        self.assertNotIn(self.changed_tag, self.removed)

    def test_an_image_a_container_uses_stays(self) -> None:
        self.assertNotIn(IN_USE, self.removed)

    def test_toolchain_images_nobody_resolves_go(self) -> None:
        self.assertEqual(self.removed, {ORPHAN, OTHER_DISTRO})

    def test_images_outside_the_toolchain_tags_are_never_touched(self) -> None:
        for image in NOT_TOOLCHAIN:
            with self.subTest(image=image):
                self.assertNotIn(image, self.removed)


if __name__ == "__main__":
    unittest.main()
