"""Lint: JavaScript never substitutes a value for an unset environment variable.

``process.env.X || <value>`` is a second source for something the deployment
already owns, and the two drift without a sound. ``playwright.config.js`` read
``process.env.PLAYWRIGHT_ACTION_TIMEOUT || 30_000`` while nothing ever set that
variable, so every run used the unscaled 30 s and no failure ever said so.

Normalising an absent variable is allowed, because it substitutes nothing:
``|| ""``, ``|| "[]"``, ``|| false`` and ``|| 0`` only let the caller test
absence itself, and falling through to another ``process.env`` entry leaves the
value with the environment rather than taking it away.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``// nocheck: env-default`` on, or directly above, the offending line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "env-default"
_FALSY = r"""(?:""|''|"\[\]"|'\[\]'|false\b|0\b|process\.env\b)"""
_DEFAULTED = re.compile(
    rf"""process\.env(?:\.\w+|\[[^\]]+\])\s*(?:\|\||\?\?)\s*(?!{_FALSY})\S"""
)


def env_defaults() -> list[str]:
    findings = []
    for path, content in iter_project_files_with_content(extensions=(".js",)):
        lines = content.splitlines()
        for number, line in enumerate(lines, start=1):
            if not _DEFAULTED.search(line):
                continue
            if is_suppressed_at(lines, number, _RULE):
                continue
            rel = Path(path).relative_to(PROJECT_ROOT)
            findings.append(f"{rel}:{number}: {line.strip()[:90]}")
    return findings


class TestNoEnvDefaultsInJavaScript(unittest.TestCase):
    def test_no_javascript_substitutes_a_value_for_an_unset_variable(self) -> None:
        findings = env_defaults()
        self.assertEqual(
            [],
            findings,
            f"environment default(s) in JavaScript ({len(findings)}). The value "
            "belongs to whoever renders the environment; a fallback here is a "
            "second source that hides an unfed variable instead of failing on "
            'it. Normalising to "" stays allowed:\n'
            + "\n".join(f"  - {f}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
