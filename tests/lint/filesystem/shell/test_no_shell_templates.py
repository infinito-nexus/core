"""Lint: a shell script ships as ``.sh``, not as ``.sh.j2``.

A templated script is opaque to every tool that reads shell. ``shellcheck``
parses Jinja as syntax errors, the repo's own ``.sh`` guards (``|| true``,
``sh -c pipefail``, inline PHP) skip the file because it is not a ``.sh``, and
nothing can execute it to test it: what runs on the host never exists in the
repository. A defect in the rendered half is found by deploying it.

The variability belongs in the invocation, not in the text. ``sys-service``
resolves ``files/shell/script.sh`` alongside ``templates/script.sh.j2``, and a
static script takes its values the way this repo's Python scripts already do:
as arguments on ``ExecStart``, or through ``Environment=``.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: shell-template`` anywhere in the first 30 lines, for a script whose
  shape itself is generated rather than its values. Put the marker BELOW the
  shebang, never above it, and prefer the Jinja comment form ``{# ... #}`` so it
  does not land in the rendered script. State what is generated.

None of the templates present when this guard landed meets that bar: each
interpolates values into a fixed script, and each is grandfathered with a marker
saying so, because converting a deployed script to argv changes what runs on the
host. The guard exists to stop the next one.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "shell-template"
_SUFFIX = ".sh.j2"


class TestNoShellTemplates(unittest.TestCase):
    def test_no_shell_script_is_a_template(self) -> None:
        findings: list[str] = []
        for path in iter_project_files(extensions=(_SUFFIX,), exclude_tests=True):
            lines = read_text(path).splitlines()
            if is_suppressed_in_head(lines, _RULE):
                continue
            findings.append(f"- {Path(path).relative_to(PROJECT_ROOT).as_posix()}")

        if findings:
            self.fail(
                "These shell scripts are Jinja templates, so shellcheck, the "
                "repository's .sh guards and every test read something other "
                "than what runs on the host:\n"
                + "\n".join(sorted(findings))
                + "\n\nFix: move the script to files/shell/ as a plain .sh and "
                "pass its values as ExecStart arguments or Environment= entries, "
                f"or mark it `nocheck: {_RULE}` in the file head when the script's "
                "shape, not just its values, is generated."
            )


if __name__ == "__main__":
    unittest.main()
