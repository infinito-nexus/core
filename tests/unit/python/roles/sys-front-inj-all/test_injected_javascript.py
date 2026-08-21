"""Injected JavaScript must still parse after ``to_one_liner`` collapses it.

``sys-front-inj-javascript`` loads a role's ``javascript.js`` or its ``.j2``
template, runs it through ``to_one_liner`` - which strips every comment and
newline - and inlines the result under a CSP hash. A script that parses only
before that collapse is served broken *with a matching hash*: the browser
rejects nothing and executes nothing, so the page loses its injection without
a single error anywhere in the deploy. Parsing the collapsed form is the only
place that failure is observable.

Jinja is not rendered. Expressions become a neutral literal and statements are
dropped, which is enough to expose an ASI break or a comment-stripping defect
without standing up an inventory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from typing import TYPE_CHECKING

from plugins.filter.text_filters import to_one_liner
from utils.cache.files import PROJECT_ROOT, read_text

if TYPE_CHECKING:
    from pathlib import Path

ROLES = PROJECT_ROOT / "roles"
PATTERNS = (
    "*/templates/javascript.js.j2",
    "*/templates/javascript.js",
    "*/files/javascript/javascript.js",
)
EXPRESSION = re.compile(r"\{\{.*?\}\}", re.DOTALL)
STATEMENT = re.compile(r"\{%.*?%\}", re.DOTALL)


def _sources() -> list[Path]:
    return sorted({path for pattern in PATTERNS for path in ROLES.glob(pattern)})


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestInjectedJavascript(unittest.TestCase):
    def test_every_injected_script_parses_after_one_lining(self) -> None:
        sources = _sources()
        self.assertTrue(
            sources, f"no injected JavaScript matched {PATTERNS} under {ROLES}"
        )

        for path in sources:
            with self.subTest(role=path.relative_to(ROLES).parts[0]):
                text = read_text(str(path))
                if path.name.endswith(".j2"):
                    text = EXPRESSION.sub("0", STATEMENT.sub("", text))
                collapsed = to_one_liner(text)
                self.assertNotIn("\n", collapsed)
                self.assertNotIn(
                    "]=]",
                    collapsed,
                    "body_filter.lua.j2 embeds the snippet as a Lua [=[ ]=] long"
                    " string; an inner ]=] closes it early and the OpenResty"
                    " config stops loading for every site on the host",
                )

                with tempfile.NamedTemporaryFile("w", suffix=".js") as handle:
                    handle.write(collapsed)
                    handle.flush()
                    proc = subprocess.run(
                        ["node", "--check", handle.name],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
