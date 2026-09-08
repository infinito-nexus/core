"""``docs/`` holds documents, not the code that writes them.

A generator parked next to its output reads as documentation, so it drifts out
of the checks that apply to code: it grows a ``__file__`` walk to find the
repository root, imports through a ``sys.path`` insert, and carries suppressions
for both. Moving it under ``cli/`` costs nothing and removes the exemptions.

Generated pages stay here; the module that renders them lives in
``cli/build/<name>/`` and runs through its own make target.
"""

from __future__ import annotations

import unittest

from utils.cache.files import iter_non_ignored_files

from . import PROJECT_ROOT

ALLOWED_SUFFIXES = frozenset({".md", ".html", ".rst"})
ALLOWED_NAMES = frozenset({".nocheck"})


def _docs_files() -> list[str]:
    """Return every non-ignored path under ``docs/``.

    Build artefacts such as ``__pycache__`` are not the subject of this rule,
    so the walk applies ``.gitignore`` rather than listing the directory raw.
    It does not ask git directly: the containerised test runner owns the
    checkout under a different uid, and git refuses such a repository outright.
    """
    docs = PROJECT_ROOT / "docs"
    return sorted(
        str(path.relative_to(PROJECT_ROOT))
        for raw in iter_non_ignored_files(root=str(PROJECT_ROOT))
        if (path := PROJECT_ROOT / raw).is_relative_to(docs)
    )


class TestDocsHoldsOnlyDocuments(unittest.TestCase):
    def test_every_tracked_file_under_docs_is_a_document(self) -> None:
        offenders = [
            path
            for path in _docs_files()
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
