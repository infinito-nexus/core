"""Lint: every module an entrypoint imports actually reaches its container.

An entrypoint imports its siblings by bare name, which resolves at runtime
against the directory the image was built from. A module that exists in the
repository but is missing from the image's ``COPY`` line, or from the task that
stages the build context, is not a broken import here: it is a
``ModuleNotFoundError`` at container start, on every surface the service backs
at once, and nothing in the repository looks at the two lists.

The import set is read from the entrypoint's source rather than listed, so a
sibling it newly imports is covered without touching this file; a sibling
reached only through another module is not. Splitting a module that has grown
past the file-size cap is exactly when the two lists fall behind, because the
split adds a file the lists were never told about.

Each subject names the role, the entrypoint, the directory its image copies
into and the task that stages the build context.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

_SUBJECTS = (
    ("svc-ai-mcp-adapter", "server.py", "/opt/adapter/", "tasks/instance.yml"),
    ("svc-ai-agent-broker", "server.py", "/opt/broker/", "tasks/00_core.yml"),
)


def python_dir(role: str) -> Path:
    """Return the directory holding a role's shipped python modules.

    Args:
        role: role directory name under ``roles/``.
    """
    return PROJECT_ROOT / "roles" / role / "files" / "python"


def imported_siblings(role: str, entrypoint: str) -> list[str]:
    """Return the sibling module file names the entrypoint imports by bare name.

    A bare ``import x`` that matches ``files/python/x.py`` is a sibling; an
    import of a standard-library or third-party name is not.

    Args:
        role: role directory name under ``roles/``.
        entrypoint: file name of the module the image runs.
    """
    source = python_dir(role) / entrypoint
    tree = ast.parse(read_text(str(source)))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            head = name.split(".")[0]
            if (python_dir(role) / f"{head}.py").is_file():
                found.add(f"{head}.py")
    return sorted(found)


def copied_modules(role: str, target: str) -> set[str]:
    """Return the file names the image's COPY line places in the service dir.

    Args:
        role: role directory name under ``roles/``.
        target: container directory the COPY line writes into.
    """
    dockerfile = PROJECT_ROOT / "roles" / role / "files" / "Dockerfile"
    pattern = re.compile(rf"^COPY\s+(?P<files>.+?)\s+{re.escape(target)}", re.MULTILINE)
    match = pattern.search(read_text(str(dockerfile)))
    return set(match["files"].split()) if match else set()


def staged_modules(role: str, task: str) -> set[str]:
    """Return the file names the staging task puts into the build context.

    Args:
        role: role directory name under ``roles/``.
        task: role-relative path of the task that stages the build context.
    """
    text = read_text(str(PROJECT_ROOT / "roles" / role / task))
    return {Path(p).name for p in re.findall(r"files/python/([\w./-]+\.py)", text)}


class TestServiceModulesStaged(unittest.TestCase):
    def test_every_imported_sibling_is_copied_into_the_image(self) -> None:
        for role, entrypoint, target, _task in _SUBJECTS:
            with self.subTest(role=role):
                copied = copied_modules(role, target)
                missing = sorted(set(imported_siblings(role, entrypoint)) - copied)
                self.assertEqual(
                    [],
                    missing,
                    f"module(s) imported by {role} but absent from the image "
                    f"COPY line {sorted(copied)}: {missing}",
                )

    def test_every_imported_sibling_is_staged_into_the_build_context(self) -> None:
        for role, entrypoint, _target, task in _SUBJECTS:
            with self.subTest(role=role):
                staged = staged_modules(role, task)
                missing = sorted(set(imported_siblings(role, entrypoint)) - staged)
                self.assertEqual(
                    [],
                    missing,
                    f"module(s) imported by {role} but never staged by "
                    f"{task} {sorted(staged)}: {missing}",
                )

    def test_nothing_is_copied_that_the_entrypoint_never_imports(self) -> None:
        for role, entrypoint, target, _task in _SUBJECTS:
            with self.subTest(role=role):
                copied = copied_modules(role, target)
                stray = sorted(
                    copied - set(imported_siblings(role, entrypoint)) - {entrypoint}
                )
                self.assertEqual(
                    [],
                    stray,
                    f"module(s) copied into the {role} image that its "
                    f"entrypoint never imports: {stray}",
                )

    def test_the_scan_finds_imported_siblings(self) -> None:
        for role, entrypoint, _target, _task in _SUBJECTS:
            with self.subTest(role=role):
                self.assertTrue(
                    imported_siblings(role, entrypoint),
                    f"the {role} entrypoint imports no sibling module, so every "
                    "rule here would pass vacuously; check that the parse still "
                    "reaches it",
                )


if __name__ == "__main__":
    unittest.main()
