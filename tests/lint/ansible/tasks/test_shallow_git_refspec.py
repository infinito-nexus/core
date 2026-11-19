"""Lint: a shallow ``git`` checkout of a pinned ref survives its next update.

Every ``git`` task that sets ``depth`` and a ``version`` other than ``HEAD``
MUST set ``refspec`` and MUST NOT set ``single_branch: true``. Every role that
hands a ``compose_repository_ref`` to the shared clone of ``sys-svc-compose``
MUST declare ``ref_kind`` on its primary entity in ``meta/services.yml`` and
MUST NOT pass ``compose_repository_refspec``. Every declared ``ref_kind`` MUST
be ``tag``, ``branch`` or ``commit`` and sit beside a ``ref`` or
``source_version``.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: shallow-git-refspec`` on the module line or the one above it,
  when the version is always a branch.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.git_refspec import REF_KIND_KEY, REF_KINDS
from utils.roles.entity.name import entity_name
from utils.roles.invocations import iter_tasks
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT
from .test_path_single_owner import module_line

_RULE = "shallow-git-refspec"

GIT_MODULES = ("git", "ansible.builtin.git", "ansible.legacy.git")
INCLUDE_MODULES = (
    "include_role",
    "import_role",
    "ansible.builtin.include_role",
    "ansible.builtin.import_role",
)

URL_KEY = "compose_repository_url"
REF_KEY = "compose_repository_ref"
PULL_KEY = "compose_repository_pull"
REFSPEC_KEY = "compose_repository_refspec"
REF_KEYS = ("ref", "source_version")
STACK_KEY = "stack"
CHECKOUT_KEY = "checkout"
CHECKOUT_REF_PATH = f"services.{STACK_KEY}.{CHECKOUT_KEY}.ref"
SET_FACT_MODULES = ("set_fact", "ansible.builtin.set_fact")

_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})
_EMPTY = re.compile(r"""^\s*(\{\{\s*(''|"")\s*\}\})?\s*$""")
_VARIABLE = re.compile(r"^\s*\{\{\s*([A-Za-z_]\w*)\s*\}\}\s*$")
_FORWARD = re.compile(
    r"lookup\(\s*'config'\s*,\s*[A-Za-z_]\w*\s*,\s*'"
    + re.escape(CHECKOUT_REF_PATH)
    + "'"
)
_INLINE_FORWARD = re.compile(
    r"^\s*\{\{\s*" + _FORWARD.pattern + r"\s*(?:,\s*(?:''|\"\")\s*)?\)\s*\}\}\s*$"
)


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() in _TRUE_WORDS


def _is_false(value: Any) -> bool:
    return value is False or str(value).strip().lower() in _FALSE_WORDS


def offenders(tasks: Any) -> list[tuple[str, str, str]]:
    """Return ``(task name, module, missing fix)`` of every shallow checkout
    whose next update crashes.

    Args:
        tasks: a parsed task file.
    """
    found: list[tuple[str, str, str]] = []
    for task in iter_tasks(tasks):
        module = next((m for m in GIT_MODULES if isinstance(task.get(m), dict)), None)
        if module is None:
            continue
        args = task[module]
        if not args.get("depth"):
            continue
        if str(args.get("version", "HEAD")).strip() == "HEAD":
            continue
        if _is_true(args.get("single_branch", False)):
            found.append((str(task.get("name", "")), module, "drop single_branch"))
        elif not args.get("refspec"):
            found.append((str(task.get("name", "")), module, "add refspec"))
    return found


def _clones(variables: dict[str, Any]) -> bool:
    if REF_KEY not in variables or _is_false(variables.get(PULL_KEY, True)):
        return False
    return not _EMPTY.match(str(variables.get(URL_KEY, "")))


def forwarded_refs(tasks: Any) -> set[str]:
    """
    Args:
        tasks: a parsed task file.

    Returns:
        the facts the task file sets from its consumer's checkout ref.
    """
    names: set[str] = set()
    for task in iter_tasks(tasks):
        facts = next(
            (task[m] for m in SET_FACT_MODULES if isinstance(task.get(m), dict)), {}
        )
        names.update(
            name for name, value in facts.items() if _FORWARD.search(str(value))
        )
    return names


def _forwards(variables: dict[str, Any], forwarded: set[str]) -> bool:
    value = str(variables.get(REF_KEY, ""))
    if _INLINE_FORWARD.match(value):
        return True
    match = _VARIABLE.match(value)
    return match is not None and match.group(1) in forwarded


def clone_offenders(tasks: Any, declared_kind: Any) -> list[tuple[str, str, str]]:
    """Return ``(task name, module, missing fix)`` of every include that hands
    a ref to the shared clone without a declared kind.

    Args:
        tasks: a parsed task file.
        declared_kind: the ``ref_kind`` of the role's primary entity, ``None``
            when it declares none.
    """
    found: list[tuple[str, str, str]] = []
    forwarded = forwarded_refs(tasks)
    for task in iter_tasks(tasks):
        module = next((m for m in INCLUDE_MODULES if m in task), None)
        variables = task.get("vars")
        if module is None or not isinstance(variables, dict):
            continue
        name = str(task.get("name", ""))
        if REFSPEC_KEY in variables:
            found.append((name, module, f"drop {REFSPEC_KEY}"))
        if (
            _clones(variables)
            and not _forwards(variables, forwarded)
            and declared_kind not in REF_KINDS
        ):
            found.append((name, module, f"declare {REF_KIND_KEY}"))
    return found


def misses_checkout_kind(role: str, services: Any) -> bool:
    """
    Args:
        role: the role name.
        services: its parsed ``meta/services.yml``.

    Returns:
        whether the role hands the stack a checkout ref without a kind.
    """
    stack = services.get(STACK_KEY) if isinstance(services, dict) else None
    checkout = stack.get(CHECKOUT_KEY) if isinstance(stack, dict) else None
    ref = checkout.get("ref") if isinstance(checkout, dict) else None
    if not ref or _EMPTY.match(str(ref)):
        return False
    return _entity_kind(role, services) not in REF_KINDS


def kind_offenders(services: Any) -> list[tuple[str, str]]:
    """Return ``(entity, problem)`` of every invalid ``ref_kind`` declaration.

    Args:
        services: a parsed ``meta/services.yml``.
    """
    found: list[tuple[str, str]] = []
    if not isinstance(services, dict):
        return found
    for entity, config in services.items():
        if not isinstance(config, dict) or REF_KIND_KEY not in config:
            continue
        kind = config[REF_KIND_KEY]
        if kind not in REF_KINDS:
            found.append(
                (
                    str(entity),
                    f"{REF_KIND_KEY} {kind!r} is not {' or '.join(REF_KINDS)}",
                )
            )
        if not any(config.get(key) for key in REF_KEYS):
            found.append(
                (str(entity), f"{REF_KIND_KEY} without {' or '.join(REF_KEYS)}")
            )
    return found


def _entity_kind(role: str, services: Any) -> Any:
    entity = services.get(entity_name(role)) if isinstance(services, dict) else None
    return entity.get(REF_KIND_KEY) if isinstance(entity, dict) else None


def _primary_entity_kind(role: str) -> Any:
    return _entity_kind(
        role,
        load_yaml_any(
            str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES),
            default_if_missing={},
        ),
    )


def _task_files() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if "/tasks/" in "/" + rel:
            found.append((path, rel))
    return found


_FORWARDED = f"{{{{ lookup('config', application_id, '{CHECKOUT_REF_PATH}', '') }}}}"


class TestShallowGitRefspec(unittest.TestCase):
    def _report(self, path: str, rel: str, found: list[tuple[str, str, str]]):
        lines = read_text(path).splitlines()
        for name, module, fix in found:
            line = module_line(lines, name, module)
            if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                continue
            yield f"- {rel}:{line}: {name or '<unnamed>'} ({fix})"

    def test_every_shallow_pinned_checkout_sets_a_refspec(self) -> None:
        findings: list[str] = []
        for path, rel in _task_files():
            findings += self._report(path, rel, offenders(load_yaml_any(path)))

        if findings:
            self.fail(
                "These shallow git checkouts of a pinned ref crash the next deploy "
                "with \"'NoneType' object has no attribute 'startswith'\" "
                "(ansible-core >= 2.21.6):\n"
                + "\n".join(findings)
                + "\n\nFix: add `refspec` (a tag `v1` takes "
                "`+refs/tags/v1:refs/tags/v1`) and drop `single_branch: true`, "
                f"or mark it `nocheck: {_RULE}` when the version is always a "
                "branch."
            )

    def test_every_shared_clone_ref_declares_its_kind(self) -> None:
        findings: list[str] = []
        for path, rel in _task_files():
            parts = rel.split("/")
            if parts[0] != "roles":
                continue
            found = clone_offenders(load_yaml_any(path), _primary_entity_kind(parts[1]))
            findings += self._report(path, rel, found)

        if findings:
            self.fail(
                f"These includes hand `{REF_KEY}` to the shared clone of "
                "sys-svc-compose, which derives the refspec from the kind the "
                "role declares:\n"
                + "\n".join(findings)
                + f"\n\nFix: set `{REF_KIND_KEY}: tag` or `{REF_KIND_KEY}: branch` "
                "beside the ref on the role's primary entity in "
                f"`{ROLE_FILE_META_SERVICES}` (check it with `git ls-remote`), "
                f"and drop `{REFSPEC_KEY}`."
            )

    def test_every_stack_checkout_ref_declares_its_kind(self) -> None:
        findings = [
            f"- {config_path.relative_to(PROJECT_ROOT)}"
            for config_path in sorted(
                (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
            )
            if misses_checkout_kind(
                config_path.parts[-3], load_yaml_any(str(config_path))
            )
        ]
        self.assertEqual(
            findings,
            [],
            f"These roles hand `{CHECKOUT_REF_PATH}` to the stack, which clones "
            "it through sys-svc-compose:\n"
            + "\n".join(findings)
            + f"\n\nFix: set `{REF_KIND_KEY}: tag` or `{REF_KIND_KEY}: branch` "
            "beside the ref on the role's primary entity.",
        )

    def test_every_declared_ref_kind_is_valid(self) -> None:
        findings: list[str] = []
        for config_path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        ):
            role = config_path.parts[-3]
            for entity, problem in kind_offenders(load_yaml_any(str(config_path))):
                findings.append(f"- {role}/{entity}: {problem}")

        self.assertEqual(findings, [], "\n".join(findings))

    def test_tag_clone_without_refspec_is_found(self) -> None:
        tasks = [
            {
                "name": "pretix",
                "git": {"repo": "r", "dest": "d", "version": "v1", "depth": 1},
            }
        ]
        self.assertEqual(offenders(tasks), [("pretix", "git", "add refspec")])

    def test_single_branch_beside_refspec_is_found(self) -> None:
        tasks = [
            {
                "ansible.builtin.git": {
                    "version": "{{ REF }}",
                    "refspec": "+refs/tags/{{ REF }}:refs/tags/{{ REF }}",
                    "single_branch": True,
                    "depth": 1,
                }
            }
        ]
        self.assertEqual(
            offenders(tasks), [("", "ansible.builtin.git", "drop single_branch")]
        )

    def test_safe_shapes_pass(self) -> None:
        tasks = [
            {
                "git": {
                    "version": "v1",
                    "refspec": "+refs/tags/v1:refs/tags/v1",
                    "depth": 1,
                }
            },
            {"git": {"repo": "r", "depth": 1}},
            {"git": {"version": "HEAD", "depth": 1}},
            {"git": {"version": "v1", "single_branch": True}},
            {"block": [{"git": {"version": "v1", "refspec": "v1", "depth": 1}}]},
        ]
        self.assertEqual(offenders(tasks), [])

    def test_task_nested_in_a_block_is_found(self) -> None:
        tasks = [{"block": [{"git": {"version": "v1", "depth": 1}}]}]
        self.assertEqual(len(offenders(tasks)), 1)

    def test_shared_clone_without_declared_kind_is_found(self) -> None:
        tasks = [
            {
                "name": "hugo",
                "include_role": {"name": "sys-svc-compose"},
                "vars": {URL_KEY: "{{ REPO }}", REF_KEY: "{{ REF }}"},
            }
        ]
        expected = [("hugo", "include_role", f"declare {REF_KIND_KEY}")]
        self.assertEqual(clone_offenders(tasks, None), expected)
        self.assertEqual(clone_offenders(tasks, "Tag"), expected)

    def test_shared_clone_passing_a_refspec_is_found(self) -> None:
        tasks = [
            {
                "block": [
                    {
                        "ansible.builtin.include_role": {"name": "sys-svc-compose"},
                        "vars": {
                            URL_KEY: "{{ REPO }}",
                            REF_KEY: "{{ REF }}",
                            REFSPEC_KEY: "+refs/tags/{{ REF }}:refs/tags/{{ REF }}",
                        },
                    }
                ]
            }
        ]
        self.assertEqual(
            clone_offenders(tasks, "tag"),
            [("", "ansible.builtin.include_role", f"drop {REFSPEC_KEY}")],
        )

    def test_shared_clone_safe_shapes_pass(self) -> None:
        declared = [
            {
                "include_role": {"name": "sys-svc-compose"},
                "vars": {URL_KEY: "{{ REPO }}", REF_KEY: "{{ REF }}"},
            }
        ]
        no_clone = [
            {
                "include_role": {"name": "sys-svc-compose"},
                "vars": {URL_KEY: "{{ '' }}", REF_KEY: "{{ '' }}", PULL_KEY: False},
            },
            {
                "include_role": {"name": "sys-svc-compose"},
                "vars": {
                    URL_KEY: "{{ REPO }}",
                    REF_KEY: "{{ REF }}",
                    PULL_KEY: "false",
                },
            },
            {"include_role": {"name": "sys-svc-compose"}, "vars": {PULL_KEY: False}},
            {"git": {"version": "v1", "refspec": "v1", "depth": 1}},
        ]
        self.assertEqual(clone_offenders(declared, "tag"), [])
        self.assertEqual(clone_offenders(declared, "branch"), [])
        self.assertEqual(clone_offenders(no_clone, None), [])

    def test_forwarded_checkout_ref_is_judged_on_its_consumer(self) -> None:
        provider = [
            {"set_fact": {"checkout_ref": _FORWARDED}},
            {
                "include_role": {"name": "sys-svc-compose"},
                "vars": {URL_KEY: "{{ checkout_url }}", REF_KEY: "{{ checkout_ref }}"},
            },
        ]
        self.assertEqual(clone_offenders(provider, None), [])
        consumer = {
            STACK_KEY: {CHECKOUT_KEY: {"url": "r", "ref": "v1"}},
            "hugo": {"source_version": "v1"},
        }
        self.assertTrue(misses_checkout_kind("web-app-hugo", consumer))
        consumer["hugo"][REF_KIND_KEY] = "Tag"
        self.assertTrue(misses_checkout_kind("web-app-hugo", consumer))
        consumer["hugo"][REF_KIND_KEY] = "tag"
        self.assertFalse(misses_checkout_kind("web-app-hugo", consumer))

    def test_checkout_ref_passed_as_an_include_param_is_judged_on_its_consumer(
        self,
    ) -> None:
        forwarded = "{{ lookup('config', stack_consumer_id, '%s', '') }}"
        provider = [
            {
                "include_role": {"name": "sys-svc-compose"},
                "vars": {
                    URL_KEY: "{{ checkout_url }}",
                    REF_KEY: forwarded % CHECKOUT_REF_PATH,
                },
            }
        ]
        self.assertEqual(clone_offenders(provider, None), [])
        for other in (
            forwarded % f"services.{STACK_KEY}.{CHECKOUT_KEY}.url",
            forwarded % "services.hugo.source_version",
            f"{{{{ lookup('config', stack_consumer_id, '{CHECKOUT_REF_PATH}', '') ~ REF }}}}",
        ):
            with self.subTest(ref=other):
                provider[0]["vars"][REF_KEY] = other
                self.assertEqual(
                    clone_offenders(provider, None),
                    [("", "include_role", f"declare {REF_KIND_KEY}")],
                )

    def test_direct_clone_beside_a_forwarded_ref_is_found(self) -> None:
        tasks = [
            {"ansible.builtin.set_fact": {"checkout_ref": _FORWARDED}},
            {
                "name": "hugo",
                "include_role": {"name": "sys-svc-compose"},
                "vars": {URL_KEY: "{{ REPO }}", REF_KEY: "{{ REF }}"},
            },
        ]
        self.assertEqual(
            clone_offenders(tasks, None),
            [("hugo", "include_role", f"declare {REF_KIND_KEY}")],
        )

    def test_checkout_without_a_ref_needs_no_kind(self) -> None:
        for checkout in ({"url": "r"}, {"url": "r", "ref": "{{ '' }}"}, "r"):
            self.assertFalse(
                misses_checkout_kind(
                    "web-app-hugo", {STACK_KEY: {CHECKOUT_KEY: checkout}, "hugo": {}}
                )
            )

    def test_invalid_ref_kind_is_found(self) -> None:
        services = {
            "bigbluebutton": {"ref": "v3.0.39", REF_KIND_KEY: "release"},
            "orphan": {"image": "nginx", REF_KIND_KEY: "tag"},
        }
        self.assertEqual(
            [entity for entity, _ in kind_offenders(services)],
            ["bigbluebutton", "orphan"],
        )

    def test_valid_ref_kinds_pass(self) -> None:
        services = {
            "bigbluebutton": {"ref": "v3.0.39", REF_KIND_KEY: "branch"},
            "hugo": {"source_version": "v0.165.0", REF_KIND_KEY: "tag"},
            "worldmonitor": {
                "ref": "e2d6809b71e942a89625bfef4c69d4a3fe8f01d1",
                REF_KIND_KEY: "commit",
            },
            "postgres": {"image": "postgres"},
        }
        self.assertEqual(kind_offenders(services), [])


if __name__ == "__main__":
    unittest.main()
