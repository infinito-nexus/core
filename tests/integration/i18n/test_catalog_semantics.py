"""Meaning-level checks the structural lints cannot see.

Both checks read the same catalogs, so they share one scan. They live in one
module on purpose: the runner distributes with ``--dist loadscope``, which
groups by module, so a scan shared across two modules would be computed once
per worker process instead of once.

Neither needs a service: the offences are decidable from the catalogs alone,
which is what keeps them here rather than in ``tests/oracle``.

Covered:
  * A machine translation byte-identical to its source. LibreTranslate answers
    200 with the request body when it has no model for a pair, when the text
    is shorter than its sentence splitter's minimum, or when a worker dies
    mid-batch. The entry is filled, carries the machine-translation comment
    and breaks no placeholder, so every lint passes while the language ships
    English.
  * One translation shared by many distinct sources. A degenerating model
    answers with one generic sentence for a whole batch and a truncated one
    answers with the first few words of everything; both leave entries that
    are filled, differ from their sources and break no placeholder. What is
    gone is the distinction between the strings.
"""

from __future__ import annotations

import functools
import unittest

from . import MAX_SHARING_SOURCES, MIN_SOURCE_CHARS, Findings, scan

MAX_REPORTED = 40


@functools.cache
def _findings() -> Findings:
    return scan()


def _report(offenders: list[str]) -> str:
    """Return the offender list, truncated to what a failure should print."""
    shown = "\n".join(f"  - {o}" for o in offenders[:MAX_REPORTED])
    return shown + ("\n  ..." if len(offenders) > MAX_REPORTED else "")


class TestCatalogSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.findings = _findings()

    def test_machine_translations_differ_from_their_source(self):
        if self.findings.echoes:
            self.fail(
                f"{len(self.findings.echoes)} machine translation(s) are "
                "byte-identical to their source, so the engine returned the "
                "input:\n"
                + _report(self.findings.echoes)
                + "\n\nFix: `make i18n-prune` those entries and re-run "
                "`make i18n-translate` for the affected languages."
            )

    def test_distinct_sources_keep_distinct_translations(self):
        if self.findings.collapses:
            self.fail(
                f"{len(self.findings.collapses)} translation(s) are shared by "
                f"more than {MAX_SHARING_SOURCES} distinct sources of at least "
                f"{MIN_SOURCE_CHARS} characters, so the engine collapsed "
                "them:\n"
                + _report(self.findings.collapses)
                + "\n\nFix: `make i18n-prune` the affected languages and re-run "
                "`make i18n-translate` with a smaller batch."
            )
