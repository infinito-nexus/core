"""``docs/`` holds documents, not the code that writes them.

A generator parked next to its output reads as documentation, so it drifts out
of the checks that apply to code: it grows a ``__file__`` walk to find the
repository root, imports through a ``sys.path`` insert, and carries suppressions
for both. Moving it under ``cli/`` costs nothing and removes the exemptions.

Generated pages stay here; the module that renders them lives in
``cli/build/<name>/`` and runs through its own make target.
"""

from __future__ import annotations

import subprocess
import unittest

from . import PROJECT_ROOT

ALLOWED_SUFFIXES = frozenset({".md", ".html", ".rst"})
ALLOWED_NAMES = frozenset({".nocheck"})


def _tracked_docs_files() -> list[str]:
    """Return every tracked path under ``docs/``.

    Untracked build artefacts such as ``__pycache__`` are not the subject of
    this rule, so the listing comes from git rather than from a directory walk.
    """
    result = subprocess.run(
        ["git", "ls-files", "docs"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


class TestDocsHoldsOnlyDocuments(unittest.TestCase):
    def test_every_tracked_file_under_docs_is_a_document(self) -> None:
        offenders = [
            path
            for path in _tracked_docs_files()
            if not path.endswith(tuple(ALLOWED_SUFFIXES))
            and path.rsplit("/", 1)[-1] not in ALLOWED_NAMES
        ]
        self.assertEqual(
            [],
            offenders,
            "docs/ carries files that are not documents: "
            f"{', '.join(sorted(offenders))}. Allowed are "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))} plus "
            f"{', '.join(sorted(ALLOWED_NAMES))}; a generator belongs under "
            "cli/build/<name>/ with a make target that writes into docs/.",
        )
