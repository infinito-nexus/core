from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from jinja2 import Environment, select_autoescape

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles" / "web-app-kix" / "templates" / "design.js.j2"
TITLE = "Acme Desk"
HARNESS = """
const vm = require("node:vm");
const script = process.argv[1];
const cases = JSON.parse(process.argv[2]);
const titles = cases.map(([pathname, title]) => {
  const document = { title, head: {}, addEventListener() {} };
  const sandbox = { document, location: { pathname }, MutationObserver: class { observe() {} } };
  vm.runInNewContext(script, sandbox);
  return document.title;
});
process.stdout.write(JSON.stringify(titles));
"""
CASES = (
    ("/auth", "Welcome to KIX", TITLE),
    ("/auth", "Willkommen bei KIX", TITLE),
    ("/kix/auth", "Welcome to KIX", TITLE),
    ("/auth", TITLE, TITLE),
    ("/home", "KIX 18", TITLE),
    ("/home", "", TITLE),
    ("/home", "Home", f"Home · {TITLE}"),
    ("/home", f"Home · {TITLE}", f"Home · {TITLE}"),
    ("/authors", "Authors", f"Authors · {TITLE}"),
)


def _render() -> str:
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.globals["lookup"] = lambda *_: {"title": TITLE}
    environment.filters["to_json"] = json.dumps
    return environment.from_string(read_text(str(TEMPLATE))).render(
        application_id="web-app-kix"
    )


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestDesignTitle(unittest.TestCase):
    def test_every_page_carries_the_configured_title(self) -> None:
        proc = subprocess.run(
            [
                "node",
                "-e",
                HARNESS,
                _render(),
                json.dumps([[path, title] for path, title, _ in CASES]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for (path, title, expected), actual in zip(
            CASES, json.loads(proc.stdout), strict=True
        ):
            with self.subTest(path=path, title=title):
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
