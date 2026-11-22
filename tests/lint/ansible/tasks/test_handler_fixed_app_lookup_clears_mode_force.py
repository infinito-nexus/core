"""A handler that resolves a fixed app must not inherit a caller's mode override.

A role that pins ``compose_mode_force`` in its vars (web-app-matrix's ansible
flavor, web-app-bigbluebutton) keeps it in scope for every handler copy loaded
inside its include chain. A lookup that reads the caller's override then
resolves the named app at the caller's mode instead of the mode that app runs
at: the OpenResty reload asked a swarm cluster for a compose container name and
skipped the reload.

So a handler task whose lookup names a fixed application clears the override
in its effective vars: its own ``vars:``, an enclosing block's, or those of the
``handlers/main.yml`` entry that includes its file by a literal path. A named
app that forces its own mode is exempt, since the override is then its own.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

ROLES = PROJECT_ROOT / "roles"
LOOKUPS = PROJECT_ROOT / "plugins" / "lookup"
READS_CALLER_OVERRIDE = re.compile(r"""\.get\(\s*["']compose_mode_force["']""")
SHARED_CONTEXT = re.compile(r"build_context\((?![^)]*honour_mode_force=False)")
INCLUDE_KEYS = (
    "include_tasks",
    "import_tasks",
    "ansible.builtin.include_tasks",
    "ansible.builtin.import_tasks",
)
BLOCK_KEYS = ("block", "rescue", "always")


def _honouring_lookups() -> set[str]:
    names = set()
    for path in LOOKUPS.glob("*.py"):
        text = read_text(str(path))
        if READS_CALLER_OVERRIDE.search(text) or SHARED_CONTEXT.search(text):
            names.add(path.stem)
    return names


def _forced_roles() -> set[str]:
    forced = set()
    for vars_main in ROLES.glob(f"*/{ROLE_FILE_VARS_MAIN}"):
        data = load_yaml_any(str(vars_main), default_if_missing={})
        if isinstance(data, dict) and str(data.get("compose_mode_force") or "").strip():
            forced.add(vars_main.relative_to(ROLES).parts[0])
    return forced


def _vars(node: dict) -> dict:
    found = node.get("vars")
    return found if isinstance(found, dict) else {}


def _included_vars(handlers_dir: Path) -> dict[Path, dict]:
    entries = load_yaml_any(str(handlers_dir / "main.yml"), default_if_missing=[])
    found: dict[Path, dict] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        for key in INCLUDE_KEYS:
            target = entry.get(key)
            if isinstance(target, dict):
                target = target.get("file")
            if isinstance(target, str) and "{{" not in target:
                found[(handlers_dir / target).resolve()] = _vars(entry)
    return found


def _tasks(items: Any, inherited: dict) -> Iterator[tuple[dict, dict]]:
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        scope = {**inherited, **_vars(item)}
        bodies = [item[key] for key in BLOCK_KEYS if key in item]
        if not bodies:
            yield item, scope
        for body in bodies:
            yield from _tasks(body, scope)


def _handler_files() -> list[Path]:
    found = []
    for raw in iter_project_files(extensions=(".yml",), exclude_tests=True):
        relative = Path(raw).relative_to(PROJECT_ROOT).parts
        if len(relative) > 3 and relative[0] == "roles" and relative[2] == "handlers":
            found.append(Path(raw))
    return sorted(found)


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _scan() -> tuple[list[str], int]:
    names = "|".join(sorted(re.escape(name) for name in _honouring_lookups()))
    call = re.compile(
        rf"""lookup\(\s*['"](?P<plugin>{names})['"]\s*,\s*['"](?P<app>[a-z0-9][a-z0-9-]*)['"]"""
    )
    forced = _forced_roles()
    included: dict[Path, dict[Path, dict]] = {}
    offenders: list[str] = []
    checked = 0
    for path in _handler_files():
        handlers_dir = ROLES / path.relative_to(ROLES).parts[0] / "handlers"
        if handlers_dir not in included:
            included[handlers_dir] = _included_vars(handlers_dir)
        tasks = load_yaml_any(str(path), default_if_missing=[])
        inherited = included[handlers_dir].get(path.resolve(), {})
        for task, scope in _tasks(tasks, inherited):
            for text in _strings(task):
                for match in call.finditer(text):
                    app = match["app"]
                    if app in forced or not (ROLES / app).is_dir():
                        continue
                    checked += 1
                    if scope.get("compose_mode_force") != "":
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}: "
                            f"{task.get('name', '<unnamed>')}: "
                            f"lookup('{match['plugin']}', '{app}', ...)"
                        )
    return offenders, checked


class TestHandlerFixedAppLookupClearsModeForce(unittest.TestCase):
    def test_container_address_is_known_to_honour_the_override(self) -> None:
        self.assertIn("container_address", _honouring_lookups())

    def test_every_fixed_app_lookup_in_a_handler_clears_the_override(self) -> None:
        offenders, checked = _scan()

        self.assertGreater(
            checked, 0, "no handler lookup names a fixed app, so nothing was checked"
        )
        self.assertEqual(
            offenders,
            [],
            f"{len(offenders)} handler lookup(s) resolve a fixed app under the "
            f'caller\'s compose_mode_force. Add `compose_mode_force: ""` to the '
            f"task's vars (or to the handlers/main.yml entry that includes it):\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
