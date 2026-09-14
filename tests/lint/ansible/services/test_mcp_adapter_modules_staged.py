"""Lint: every module the adapter imports actually reaches the container.

``server.py`` imports its siblings by bare name, which resolves at runtime
against the directory the image was built from. A module that exists in the
repository but is missing from the image's ``COPY`` line, or from the task that
stages the build context, is not a broken import here: it is a
``ModuleNotFoundError`` at container start, on every adapter-backed surface at
once, and nothing in the repository looks at the two lists.

The import set is read from the source rather than listed, so a new sibling is
covered the moment it is imported.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

_ADAPTER = PROJECT_ROOT / "roles" / "svc-ai-mcp-adapter"
_PYTHON_DIR = _ADAPTER / "files" / "python"
_ENTRYPOINT = _PYTHON_DIR / "server.py"
_DOCKERFILE = _ADAPTER / "files" / "Dockerfile"
_INSTANCE = _ADAPTER / "tasks" / "instance.yml"

_COPY = re.compile(r"^COPY\s+(?P<files>.+?)\s+/opt/adapter/", re.MULTILINE)


def imported_siblings() -> list[str]:
    """Return the sibling module file names ``server.py`` imports by bare name.

    A bare ``import x`` that matches ``files/python/x.py`` is a sibling; an
    import of a standard-library or third-party name is not.
    """
    tree = ast.parse(read_text(str(_ENTRYPOINT)))
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
            if (_PYTHON_DIR / f"{head}.py").is_file():
                found.add(f"{head}.py")
    return sorted(found)


def copied_modules() -> set[str]:
    """Return the file names the image's COPY line places in the adapter dir."""
    match = _COPY.search(read_text(str(_DOCKERFILE)))
    return set(match["files"].split()) if match else set()


def staged_modules() -> set[str]:
    """Return the file names the instance task stages into the build context."""
    text = read_text(str(_INSTANCE))
    return {Path(p).name for p in re.findall(r"files/python/([\w./-]+\.py)", text)}


class TestMcpAdapterModulesStaged(unittest.TestCase):
    def test_every_imported_sibling_is_copied_into_the_image(self) -> None:
        missing = sorted(set(imported_siblings()) - copied_modules())
        self.assertEqual(
            [],
            missing,
            f"module(s) imported by the adapter but absent from the image "
            f"COPY line {sorted(copied_modules())}: {missing}",
        )

    def test_every_imported_sibling_is_staged_into_the_build_context(self) -> None:
        missing = sorted(set(imported_siblings()) - staged_modules())
        self.assertEqual(
            [],
            missing,
            f"module(s) imported by the adapter but never staged by the "
            f"instance task {sorted(staged_modules())}: {missing}",
        )

    def test_nothing_is_copied_that_the_entrypoint_never_imports(self) -> None:
        entrypoint = _ENTRYPOINT.name
        stray = sorted(copied_modules() - set(imported_siblings()) - {entrypoint})
        self.assertEqual(
            [],
            stray,
            f"module(s) copied into the image that nothing imports: {stray}",
        )

    def test_the_scan_finds_imported_siblings(self) -> None:
        self.assertTrue(
            imported_siblings(),
            "the adapter entrypoint imports no sibling module, so every rule "
            "here would pass vacuously; check that the parse still reaches it",
        )


if __name__ == "__main__":
    unittest.main()
