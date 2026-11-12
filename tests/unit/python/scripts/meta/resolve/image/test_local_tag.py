"""Contract of the local image tag: ``<primary checkout name>/<distro>:<input hash>``."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.unit.python.scripts.image._checkout import (
    DISTRO,
    git,
    loaded_env,
    resolve_tag,
    stub_docker,
    toolchain_checkout,
)

TAG_RE = re.compile(rf"^primary/{DISTRO}:[0-9a-f]{{16}}$")


class TestLocalTag(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        stub_docker(cls.base)
        cls.primary = toolchain_checkout(cls.base)
        cls.worktree = cls.base / "linked-worktree"
        git(cls.primary, "worktree", "add", "--quiet", "--detach", str(cls.worktree))
        cls.env = loaded_env(cls.base)
        cls.baseline = resolve_tag(cls.primary, cls.env)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _scratch_worktree(self, name: str) -> Path:
        path = self.base / name
        git(self.primary, "worktree", "add", "--quiet", "--detach", str(path))
        return path

    def test_the_tag_names_the_primary_checkout_the_distro_and_a_hash(self) -> None:
        self.assertRegex(self.baseline, TAG_RE)

    def test_two_checkouts_with_equal_inputs_resolve_the_same_tag(self) -> None:
        self.assertEqual(resolve_tag(self.worktree, self.env), self.baseline)

    def test_a_change_outside_the_inputs_keeps_the_tag(self) -> None:
        checkout = self._scratch_worktree("outside-change")
        (checkout / "Makefile").write_text("probe:\n\ttrue\n")
        (checkout / "untracked-dir").mkdir()
        (checkout / "untracked-dir" / "notes.txt").write_text("probe\n")
        self.assertEqual(resolve_tag(checkout, self.env), self.baseline)

    def test_a_change_inside_the_inputs_changes_the_tag(self) -> None:
        checkout = self._scratch_worktree("inside-change")
        venv = checkout / "scripts/install/venv.sh"
        text = venv.read_text()  # nocheck: cache-read  tempdir copy the test edits
        venv.write_text(text + "\n# probe\n")
        self.assertNotEqual(resolve_tag(checkout, self.env), self.baseline)

    def test_a_new_file_inside_a_copied_directory_changes_the_tag(self) -> None:
        checkout = self._scratch_worktree("inside-new-file")
        (checkout / "requirements" / "probe.txt").write_text("probe\n")
        self.assertNotEqual(resolve_tag(checkout, self.env), self.baseline)

    def test_a_dockerfile_change_changes_the_tag(self) -> None:
        checkout = self._scratch_worktree("dockerfile-change")
        dockerfile = checkout / "Dockerfile"
        text = dockerfile.read_text()  # nocheck: cache-read  tempdir copy
        dockerfile.write_text(text + "\nLABEL probe=1\n")
        self.assertNotEqual(resolve_tag(checkout, self.env), self.baseline)

    def test_a_build_argument_changes_the_tag(self) -> None:
        for key, value in (
            ("INFINITO_VENV_DIR", "/opt/venvs/other"),
            ("INFINITO_SRC_DIR", "/opt/src/other"),
            ("INFINITO_PARENT_IMAGE", "ghcr.io/example/pkgmgr-debian:latest"),
        ):
            with self.subTest(key=key):
                env = loaded_env(self.base, **{key: value})
                self.assertNotEqual(resolve_tag(self.primary, env), self.baseline)

    def test_the_parent_image_digest_changes_the_tag(self) -> None:
        moved = loaded_env(self.base, STUB_PARENT_ID="sha256:parent-b")
        absent = loaded_env(self.base, STUB_PARENT_ID="")
        self.assertNotEqual(resolve_tag(self.primary, moved), self.baseline)
        self.assertNotEqual(resolve_tag(self.primary, absent), self.baseline)
        self.assertRegex(resolve_tag(self.primary, absent), TAG_RE)

    def test_a_build_argument_the_toolchain_stage_ignores_keeps_the_tag(self) -> None:
        env = loaded_env(self.base, NIX_CONFIG="access-tokens = github.com=probe")
        self.assertEqual(resolve_tag(self.primary, env), self.baseline)


if __name__ == "__main__":
    unittest.main()
