"""Flag ``timeout`` passed to Playwright predicates that ignore it.

``locator.isVisible()`` and ``locator.isHidden()`` declare the option
``@deprecated This option is ignored`` in playwright-core's own types: both
return immediately and never wait. A call written as
``isVisible({ timeout: resolveTimeout(10_000) })`` therefore measures the DOM
at that instant, while reading to a human as if it waited ten seconds.

Usually the argument is merely dead. Sometimes it hides a race: in
``personas/admin.js`` the pattern judged an SPA ~10 ms after a credential
submit and reported the still-in-flight login button as a failed OIDC token
exchange, which is a false negative, not a flake.

The rule does not prescribe the repair, because the two repairs differ in
cost. Verify per site what the call was meant to do:

* a presence check ("is it there right now?") keeps its exact meaning once
  the dead argument is removed;
* a call that was meant to wait needs ``waitFor({ state: "visible" })`` or
  ``waitFor({ state: "hidden" })`` — which spends real wall-clock, multiplied
  by the onion timeout factor, against a CI budget that already kills jobs.

The sibling predicates ``isChecked``/``isDisabled``/``isEditable``/
``isEnabled`` take a REAL timeout and are deliberately not matched.

Per-line opt-out: ``// nocheck: playwright-ignored-timeout`` on the offending
line or the immediately preceding one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "playwright-ignored-timeout"

_IGNORED_TIMEOUT = re.compile(r"\.is(?:Visible|Hidden)\s*\(\s*\{[^}]*\btimeout\b")


class TestPlaywrightIgnoredTimeout(unittest.TestCase):
    def test_no_timeout_on_immediate_predicates(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(
            extensions=(".js",),
            exclude_tests=True,
            exclude_dirs=("docs", "node_modules"),
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path_str).splitlines()
            for lineno, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if stripped.startswith(("//", "*", "/*")):
                    continue
                if not _IGNORED_TIMEOUT.search(line):
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                offenders.append(f"{rel}:{lineno}: {stripped}")

        if offenders:
            self.fail(
                f"{len(offenders)} call(s) pass `timeout` to a Playwright "
                "predicate that ignores it. isVisible()/isHidden() return "
                "immediately (playwright-core types: `@deprecated This option "
                "is ignored`), so each of these measures the DOM at that "
                "instant while reading as if it waited. Most are probably dead "
                "arguments; verify each site rather than sweeping. A presence "
                "check keeps its meaning without the argument, whereas a call "
                "that was meant to wait needs waitFor({state}) and costs real "
                f"wall-clock. Deliberate instant checks take `// nocheck: {_RULE}` "
                "on the offending or preceding line.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
