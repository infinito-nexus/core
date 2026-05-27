#!/usr/bin/env python3

"""
Integration test: ensure no Jinja variables are used in handler *names*.

Why this policy?
- Handler identifiers should be stable strings. If you ever notify by handler
  name (instead of a dedicated `listen:` key), a templated name can fail to
  resolve or silently not match what `notify` referenced.
- Even when `listen:` is used (recommended), variable-laden names make logs and
  tooling brittle and can trigger undefined-variable errors at parse/run time.
- Keeping handler names static improves reliability, debuggability, and
  compatibility with analysis tools.

Allowed:
- You may still template other fields or use `listen:` for dynamic trigger
  routing; just keep the handler’s `name` static text.

This test scans: roles/*/handlers/main.yml
"""

import glob
import re
import unittest

from utils.cache.yaml import load_yaml_all
from utils.roles.mapping import ROLE_FILE_HANDLERS_MAIN

try:
    import yaml  # PyYAML
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required to run this test. Install with: pip install pyyaml"
    ) from exc


JINJA_VAR_PATTERN = re.compile(r"{{.*?}}")  # minimal check for any templating


def _iter_tasks(node):
    """
    Yield all task-like dicts from a loaded YAML node, descending into common
    task containers (`block`, `rescue`, `always`), just in case.
    """
    if isinstance(node, dict):
        # If this dict looks like a task (has 'name' or a module key), yield it.
        if any(k in node for k in ("name", "action")):
            yield node

        # Dive into known task containers (handlers can include blocks too).
        for key in ("block", "rescue", "always"):
            if key in node and isinstance(node[key], list):
                for item in node[key]:
                    yield from _iter_tasks(item)

    elif isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)


class StaticHandlerNamesTest(unittest.TestCase):
    """
    Ensures handler names are static strings (no Jinja variables like {{ ... }}).
    """

    def test_no_templated_names_in_handlers(self):
        from . import PROJECT_ROOT

        pattern = str(PROJECT_ROOT / "roles" / "*" / ROLE_FILE_HANDLERS_MAIN)

        violations = []

        for handler_path in sorted(glob.glob(pattern)):  # nocheck: project-walk
            # Load possibly multi-document YAML safely
            try:
                docs = list(load_yaml_all(handler_path))
            except FileNotFoundError:
                continue
            except yaml.YAMLError as e:
                violations.append(f"{handler_path} -> YAML parse error: {e}")
                continue

            for doc in docs:
                for task in _iter_tasks(doc):
                    name = task.get("name")
                    if not isinstance(name, str):
                        # ignore unnamed or non-string names
                        continue
                    if JINJA_VAR_PATTERN.search(name):
                        # Compose a clear, actionable message
                        listen = task.get("listen")
                        listen_hint = (
                            ""
                            if listen
                            else " Consider using a static handler name and, if you need flexible triggers, add a static `listen:` key that your tasks `notify`."
                        )
                        violations.append(
                            f"{handler_path} -> Handler name contains variables: {name!r}\n"
                            "Reason: Handler names must be static. Using Jinja variables in the name "
                            "can break handler resolution (when notified by name), produces unstable logs, "
                            "and may cause undefined-variable errors. Keep the handler `name` constant."
                            f"{listen_hint}"
                        )

        if violations:
            self.fail(
                "Templated handler names are not allowed.\n\n" + "\n\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
