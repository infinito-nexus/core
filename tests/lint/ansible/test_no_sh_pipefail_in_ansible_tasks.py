from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Iterable

import yaml

from utils.cache.files import iter_project_files_with_content, read_text


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


COMMAND_KEYS = frozenset({"command", "ansible.builtin.command"})
SHELL_KEYS = frozenset({"shell", "ansible.builtin.shell"})
EXECUTABLE_AWARE_KEYS = COMMAND_KEYS | SHELL_KEYS

# Relative, POSIX-style path to the group_vars file that owns the global
# shell-executable setting. Kept as a constant because the
# `ansible_shell_executable` assertion is load-bearing: the rest of the
# codebase relies on this single definition so tasks can use
# bash-only `set -o pipefail` without repeating `args.executable` per task.
GLOBAL_GROUP_VARS_PATH = "group_vars/all/00_general.yml"


def _contains_pipefail(value: Any) -> bool:
    if isinstance(value, str):
        return "pipefail" in value
    if isinstance(value, list):
        return any(_contains_pipefail(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_pipefail(v) for v in value.values())
    return False


def _is_shell_flag(s: str) -> bool:
    # Matches -c, -lc, -ec, -euc, -leo, -eco, -euco, ...
    # i.e. a POSIX short-option bundle that requests `command` mode (`c`).
    return s.startswith("-") and "c" in s[1:]


def _argv_has_sh_with_pipefail_body(argv: Iterable[Any]) -> bool:
    """True iff argv invokes `sh <-c|-lc|...>` with a body that uses `pipefail`.

    Covers both direct runner-side invocation (`[sh, -lc, body]`) and the
    container-exec form (`[container, exec, ..., sh, -lc, body]`).
    """
    items = list(argv) if argv is not None else []
    for i, item in enumerate(items):
        if not isinstance(item, str) or item != "sh":
            continue
        nxt = items[i + 1] if i + 1 < len(items) else None
        if not isinstance(nxt, str) or not _is_shell_flag(nxt):
            continue
        for body in items[i + 2 :]:
            if _contains_pipefail(body):
                return True
    return False


def _is_non_bash_executable(value: Any) -> bool:
    """True iff `value` is a string that looks like a shell path and does
    NOT end in `bash`. Non-string/absent values are ignored (task did not
    override the executable)."""
    if not isinstance(value, str):
        return False
    return not value.rstrip("/").endswith("bash")


def _iter_candidate_dicts(node: Any) -> Iterable[dict]:
    """Yield every dict in the YAML tree. A task is always a dict; nesting
    varies (plays → tasks, include_tasks, block/rescue/always, handlers, …).
    Walking every dict keeps the scan schema-agnostic."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_candidate_dicts(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_candidate_dicts(item)


def _scan_doc(rel_path: str, doc: Any, findings: list[tuple[str, str]]) -> None:
    for task in _iter_candidate_dicts(doc):
        for key in COMMAND_KEYS & task.keys():
            mod = task[key]
            if not isinstance(mod, dict):
                continue
            if _argv_has_sh_with_pipefail_body(mod.get("argv")):
                findings.append(
                    (
                        rel_path,
                        f"`{key}`: argv invokes `sh -lc` (or similar) with "
                        "`pipefail` in the script body — use `bash` instead.",
                    )
                )

        # Per-task override of the shell executable MUST NOT point at a
        # non-bash shell. The global `ansible_shell_executable: /bin/bash`
        # only wins as long as nothing overrides it locally.
        if EXECUTABLE_AWARE_KEYS & task.keys():
            args = task.get("args")
            if isinstance(args, dict):
                exe = args.get("executable")
                if _is_non_bash_executable(exe):
                    findings.append(
                        (
                            rel_path,
                            f"`args.executable: {exe}` overrides the global "
                            "`ansible_shell_executable: /bin/bash` with a "
                            "non-bash shell — remove the override or set "
                            "`/bin/bash` explicitly.",
                        )
                    )


class TestNoShPipefailInAnsibleTasks(unittest.TestCase):
    REPO_ROOT = repo_root()

    def test_ansible_tasks_stay_on_bash(self) -> None:
        """
        Ansible `shell`/`command` tasks MUST stay on bash.

        Two antipatterns are forbidden:

        1. `command` tasks MUST NOT pass `sh` as argv[0] (or anywhere in
           an argv chain like `[container, exec, …, sh, -lc, body]`)
           together with a body that uses `pipefail`. Root cause:
           `set -o pipefail` is a bash/ksh feature and is NOT in POSIX.
           On Debian/Ubuntu `/bin/sh` is dash, which aborts with
           `sh: 1: set: Illegal option -o pipefail`. Explicit `sh` in
           argv forces that behaviour regardless of the host distro.
        2. Any `shell`/`command` task MUST NOT set `args.executable` to
           a non-bash shell (e.g. `/bin/sh`, `/bin/dash`). That would
           silently override the global
           `ansible_shell_executable: /bin/bash` default and
           re-introduce the dash trap for that task only.

        Regression that motivated this guard:
        https://github.com/infinito-nexus/core/issues/194.
        """
        findings: list[tuple[str, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(self.REPO_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            try:
                docs = list(yaml.safe_load_all(content))
            except yaml.YAMLError:
                continue
            for doc in docs:
                _scan_doc(rel, doc, findings)

        if findings:
            formatted = "\n".join(
                f"- {path}: {msg}" for path, msg in sorted(set(findings))
            )
            self.fail(
                "Found Ansible tasks that violate the bash-only shell "
                "policy. Every `shell`/`command` task MUST resolve to "
                "bash so that `set -o pipefail` and related bash features "
                "work on every distro.\n"
                "Fix: for `command`, replace argv[0] `sh` with `bash`; "
                "for `args.executable` overrides, either drop the "
                "override (global default is `/bin/bash`) or set "
                "`/bin/bash` explicitly.\n\n"
                f"{formatted}"
            )

    def test_global_ansible_shell_executable_is_bash(self) -> None:
        """
        `ansible_shell_executable` MUST be set globally to `/bin/bash` in
        `group_vars/all/`.

        Rationale: the `shell` module's default executable is the target's
        `/bin/sh`, which is dash on Debian/Ubuntu and therefore aborts any
        task body that uses `set -o pipefail`. Defining the bash default
        once at group-level lets every `shell: | … pipefail …` task work
        on every distro without repeating `args.executable: /bin/bash`
        per task. This test is the guard that prevents a silent removal
        of that single definition from re-introducing the
        infinito-nexus/core#194 class of bugs.
        """
        path = self.REPO_ROOT / GLOBAL_GROUP_VARS_PATH
        self.assertTrue(
            path.is_file(),
            f"Expected {GLOBAL_GROUP_VARS_PATH} to exist with "
            "`ansible_shell_executable: /bin/bash`.",
        )
        data = yaml.safe_load(read_text(str(path))) or {}
        value = data.get("ansible_shell_executable")
        self.assertEqual(
            value,
            "/bin/bash",
            f"{GLOBAL_GROUP_VARS_PATH} must define "
            "`ansible_shell_executable: /bin/bash` (found: "
            f"{value!r}). This single definition is what keeps every "
            "`shell: | … set -o pipefail …` task portable across dash- "
            "and bash-based distros. If you change the path, update all "
            "consumers; if you remove the key, every shell task with "
            "`pipefail` becomes a latent dash bug.",
        )


if __name__ == "__main__":
    unittest.main()
