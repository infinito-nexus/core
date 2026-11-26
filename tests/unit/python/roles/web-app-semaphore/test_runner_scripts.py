from __future__ import annotations

import fnmatch
import glob
import os
import re
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-semaphore"
FILES = ROLE_DIR / "files"
REPOSITORY = FILES / "shell" / "repository"
SOURCE_TREES = ("shell", "python", "opentofu")
CALLED = re.compile(r"\$\{here\}/\.\./\.\./(python/[A-Za-z0-9_]+\.py)")


def glob_matches(path: str, pattern: str) -> bool:
    """Args:
    path: an absolute project file path.
    pattern: an absolute, non-recursive glob pattern.

    Returns:
        Whether ``glob.glob(pattern)`` yields ``path``: component by component,
        case-sensitive, a wildcard never crossing ``/`` and never matching a
        name with a leading dot unless the pattern component has one too.
    """
    names = Path(path).parts
    parts = Path(pattern).parts
    return len(names) == len(parts) and all(
        fnmatch.fnmatchcase(name, part)
        and (not name.startswith(".") or part.startswith("."))
        for name, part in zip(names, parts, strict=True)
    )


def covered(globs: list[str]) -> set[str]:
    """Args:
    globs: ``SEMAPHORE_RUNNER_SOURCE_GLOBS``, relative to the role's ``files``.

    Returns:
        The files those globs match, relative to ``files``, with the semantics
        of Ansible's ``fileglob``: ``glob.glob``, files only.
    """
    return {
        Path(path).relative_to(FILES).as_posix()
        for pattern in globs
        for path in iter_project_files()
        if glob_matches(path, str(FILES / pattern))
    }


def uncovered_files(globs: list[str]) -> list[str]:
    """Args:
    globs: ``SEMAPHORE_RUNNER_SOURCE_GLOBS``.

    Returns:
        Every file of the trees the runner image runs or bakes that no glob
        matches, so a change to it would not rebuild the runner.
    """
    matched = covered(globs)
    trees = tuple(f"{FILES / tree}{os.sep}" for tree in SOURCE_TREES)
    return sorted(
        relative
        for path in iter_project_files()
        if path.startswith(trees)
        and (relative := Path(path).relative_to(FILES).as_posix()) not in matched
    )


def uncovered_calls(globs: list[str]) -> list[str]:
    """Args:
    globs: ``SEMAPHORE_RUNNER_SOURCE_GLOBS``.

    Returns:
        Every python file a repository script calls that no glob matches.
    """
    matched = covered(globs)
    return [
        f"{script.name} calls {target}"
        for script in sorted(REPOSITORY.glob("*.sh"))
        for target in CALLED.findall(read_text(str(script)))
        if target not in matched
    ]


class TestRunnerSourcesDigest(unittest.TestCase):
    def setUp(self) -> None:
        variables = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
        self.globs = variables["SEMAPHORE_RUNNER_SOURCE_GLOBS"]

    def test_every_called_python_file_feeds_the_runner_digest(self) -> None:
        self.assertEqual(uncovered_calls(self.globs), [])

    def test_every_file_the_runner_runs_or_bakes_feeds_the_digest(self) -> None:
        self.assertEqual(uncovered_files(self.globs), [])

    def test_negative_control_the_shell_glob_alone_misses_the_python_files(  # nocheck: test.text-presence -- runs uncovered_calls on a planted glob list
        self,
    ) -> None:
        findings = uncovered_calls(["shell/repository/*"])
        self.assertIn("members.sh calls python/semaphore_members.py", findings)
        self.assertIn("provision.sh calls python/provision.py", findings)

    def test_negative_control_flat_globs_miss_packages_and_lock_files(self) -> None:
        findings = uncovered_files(
            ["shell/repository/*", "shell/opentofu/*", "python/*", "opentofu/*"]
        )
        self.assertIn("python/provision/inputs.py", findings)
        self.assertIn("opentofu/roots/hetzner/.terraform.lock.hcl", findings)
        self.assertIn("opentofu/records/.terraform.lock.hcl", findings)

    def test_negative_control_a_star_skips_dotfiles_like_glob(self) -> None:
        self.assertNotIn(
            "opentofu/records/.terraform.lock.hcl", covered(["opentofu/records/*"])
        )
        self.assertIn(
            "opentofu/records/.terraform.lock.hcl", covered(["opentofu/records/.*"])
        )

    def test_matching_needs_no_python_3_13_glob_api(self) -> None:
        with mock.patch.dict(glob.__dict__):
            glob.__dict__.pop("translate", None)
            self.assertIn("python/provision.py", covered(["python/*"]))


if __name__ == "__main__":
    unittest.main()
