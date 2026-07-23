"""Every relative include_tasks / import_tasks / include_vars path inside a
role's tasks/ must resolve to a real file through ansible's search bases.

A task file moved into a subdir (e.g. by a renumbering refactor) otherwise
leaves a dangling include that only surfaces when that code path runs at
deploy time. include_tasks/import_tasks resolve relative to the including file's
directory (and the playbook's tasks/ for shared helpers); include_vars resolves
against the role's vars/ and defaults/.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any

_TASK_INCLUDES = frozenset({"include_tasks", "import_tasks"})
_VARS_INCLUDES = frozenset({"include_vars"})


def _file_ref(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        ref = value.get("file")
        return ref.strip() if isinstance(ref, str) else None
    return None


def _walk_tasks(node: object):
    if isinstance(node, list):
        for item in node:
            yield from _walk_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            child = node.get(key)
            if child:
                yield from _walk_tasks(child)


def _role_dir(f: Path) -> Path:
    parts = f.parts
    idx = parts.index("roles")
    return Path(*parts[: idx + 2])


def _tasks_root(f: Path) -> Path:
    parts = f.parts
    return Path(*parts[: parts.index("tasks") + 1])


def _resolves(ref: str | None, f: Path, *, vars_include: bool) -> bool:
    if not ref or ref.startswith("/") or "{{" in ref:
        return True
    role = _role_dir(f)
    if vars_include:
        bases = (role / "vars", role / "defaults", f.parent, role)
    else:
        bases = (f.parent, _tasks_root(f), PROJECT_ROOT / "tasks", PROJECT_ROOT)
    return any((base / ref).is_file() for base in bases)


class TestRelativeIncludesResolve(unittest.TestCase):
    def test_relative_includes_resolve(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".yml", ".yaml")):
            f = Path(path_str)
            posix = f.as_posix()
            if "/roles/" not in posix or "/tasks/" not in posix:
                continue
            try:
                doc = load_yaml_any(path_str, default_if_missing=None)
            except (OSError, ValueError):
                continue
            for task in _walk_tasks(doc):
                for key, value in task.items():
                    short = key.rsplit(".", 1)[-1]
                    if short in _TASK_INCLUDES:
                        vars_include = False
                    elif short in _VARS_INCLUDES:
                        vars_include = True
                    else:
                        continue
                    ref = _file_ref(value)
                    if not _resolves(ref, f, vars_include=vars_include):
                        offenders.append(
                            f"{f.relative_to(PROJECT_ROOT).as_posix()}: {short}: {ref}"
                        )
        self.assertEqual(
            [],
            offenders,
            f"{len(offenders)} unresolvable relative include/vars path(s); a moved "
            "task or vars file left a dangling reference:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
