"""Handler entry points carry a static name.

An entry that declares `listen:` is the notification target of a role, and its
name is what an operator reads in the play output and greps for in a failed
run. Templating that name buys nothing -- the `listen:` topic already carries
every dynamic decision -- and costs a stable log line, plus an
undefined-variable error whenever the play reaches the handler with the
variable unset.

Scope: every `roles/*/handlers/*.yml`, not only `main.yml`, so a role that
splits its handlers by deploy mode is covered too. Sub-tasks *inside* an
included handler file are exempt: nothing notifies them, so their names are
free to name the thing they act on (`Connect '{{ CONTAINER }}' to ...`).

Which topic a notify may bind to, and how those topics are spelled, is the
subject of `test_invoked.py`.
"""

import re
import unittest

from utils.cache.yaml import load_yaml_all

from . import PROJECT_ROOT

JINJA_VAR_PATTERN = re.compile(r"{{.*?}}")


def handler_entries():
    """Every ``listen:``-bearing entry of every handlers file, with its path."""
    for path in sorted((PROJECT_ROOT / "roles").glob("*/handlers/*.yml")):
        try:
            docs = list(load_yaml_all(str(path)))
        except Exception as error:
            yield path, {"name": f"YAML parse error: {error}", "listen": True}
            continue
        for doc in docs or []:
            for entry in doc or []:
                if isinstance(entry, dict) and "listen" in entry:
                    yield path, entry


class StaticHandlerNamesTest(unittest.TestCase):
    def test_no_templated_names_in_handlers(self) -> None:
        violations = [
            f"{path.relative_to(PROJECT_ROOT).as_posix()}: {entry['name']!r}"
            for path, entry in handler_entries()
            if isinstance(entry.get("name"), str)
            and JINJA_VAR_PATTERN.search(entry["name"])
        ]
        self.assertEqual(
            violations,
            [],
            "Handler entry point(s) with a templated name. Keep the name a "
            "constant and let the static 'listen:' topic carry the routing:\n"
            + "\n".join(f"  {v}" for v in violations),
        )


if __name__ == "__main__":
    unittest.main()
