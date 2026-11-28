from __future__ import annotations

import re
import unittest
from pathlib import Path

from ansible.errors import AnsibleUndefinedVariable
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT as WALKED_ROOT
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

SYNC = "tasks/utils/rbac/sync.yml"
REGISTER = "tasks/utils/rbac/sync/register.yml"
COLLECT = "tasks/utils/rbac/sync/collect_role.yml"
MEMBERS = "tasks/utils/rbac/members.yml"
USERS = "tasks/utils/rbac/users.yml"
TARGETS = (SYNC, REGISTER, COLLECT, MEMBERS, USERS)
READERS = (MEMBERS, USERS)
PARAM = re.compile(r"^# Param (\w+):", re.MULTILINE)
NESTED = ("block", "rescue", "always")
SEARCH = "community.general.ldap_search"
LOGINS = ["uid", "mail", "cn", "entryUUID"]
FIXTURES = {
    "application_id": "web-app-example",
    "MASK_CREDENTIALS_IN_LOGS": False,
    "LDAP": {
        "USER": {
            "ATTRIBUTES": {
                "ID": "uid",
                "MAIL": "mail",
                "FULLNAME": "cn",
                "UUID": "entryUUID",
                "STREET": "street",
                "POSTAL_CODE": "postalCode",
                "LOCALITY": "l",
                "REGION": "st",
                "COUNTRY": "c",
                "PHOTO": "jpegPhoto",
            }
        }
    },
}
KNOWN_DIRECT_CALLERS = {
    "roles/web-app-mailu/tasks/02_manager_ops/post_bootstrap_ops.yml": MEMBERS,
    "roles/web-app-friendica/tasks/00_core.yml": MEMBERS,
    f"roles/web-svc-xmpp/{ROLE_FILE_TASKS_MAIN}": MEMBERS,
    "roles/web-app-peertube/tasks/rbac/provision.yml": COLLECT,
}


def _params(target: str) -> set[str]:
    return set(PARAM.findall(read_text(str(PROJECT_ROOT / target))))


def _target(value: object) -> str:
    """Return the util an ``include_tasks`` value names, or an empty string.

    Args:
        value: the ``include_tasks`` argument, absolute through ``path_absolute``
            or relative to a role's ``tasks/`` directory.
    """
    text = str(value)
    for target in TARGETS:
        if target in text or text == target.removeprefix("tasks/"):
            return target
    return ""


def _includes(tasks: object) -> list[tuple[dict, str]]:
    """Return ``(task, util)`` of every task, nested blocks included, that includes a util.

    Args:
        tasks: a parsed task file.
    """
    found = []
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        for key in ("ansible.builtin.include_tasks", "include_tasks"):
            target = _target(task.get(key, ""))
            if target:
                found.append((task, target))
        for key in NESTED:
            found.extend(_includes(task.get(key)))
    return found


def _scope(task: dict) -> dict:
    """Return the variables an include task hands its util.

    Args:
        task: the include task.
    """
    passed = dict(task.get("vars") or {})
    if "loop" in task:
        loop_var = (task.get("loop_control") or {}).get("loop_var", "item")
        passed[loop_var] = "administrator"
    return passed


def _roots() -> dict[str, list[tuple[dict, str]]]:
    roots = {}
    for path, content in iter_project_files_with_content(
        extensions=(".yml",), exclude_tests=True
    ):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if rel in TARGETS or not any(
            target.removeprefix("tasks/") in content for target in TARGETS
        ):
            continue
        includes = _includes(load_yaml_str(content))
        if includes:
            roots[rel] = includes
    return roots


def _chains(target: str, scope: dict, via: tuple[str, ...]):
    """Yield ``(via, util, scope, missing)`` for ``target`` and every util it includes.

    Args:
        target: the included util.
        scope: the variables in effect inside it.
        via: the include chain so far, for the failure message.
    """
    yield via, target, scope, sorted(_params(target) - set(scope))
    if target in READERS:
        return
    tasks = load_yaml_str(read_text(str(PROJECT_ROOT / target)))
    for task, sub in _includes(tasks):
        yield from _chains(sub, {**scope, **_scope(task)}, (*via, sub))


def _render(expression: object, scope: dict) -> object:
    variables = {**FIXTURES, **{key: _trusted(value) for key, value in scope.items()}}
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _trusted(value: object) -> object:
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    return _trust_as_template(value) if isinstance(value, str) else value


def _reader_tasks(reader: str) -> list[dict]:
    return load_yaml_str(read_text(str(PROJECT_ROOT / reader)))


class TestEveryIncludeOfTheMemberUtilsPassesItsParameters(unittest.TestCase):
    def test_the_walk_covers_this_checkout(self) -> None:
        self.assertEqual(Path(WALKED_ROOT).resolve(), PROJECT_ROOT)

    def test_the_utils_document_the_attribute_parameters(self) -> None:  # nocheck: test.text-presence -- non-vacuity guard: the parsed Param docs drive the include-parameter lint below  # fmt: skip
        self.assertIn("rbac_sync_attributes", _params(SYNC))
        self.assertIn("rbac_sync_attributes", _params(COLLECT))
        self.assertIn("rbac_members_attributes", _params(MEMBERS))
        self.assertIn("rbac_users_attributes", _params(USERS))

    def test_the_known_direct_callers_are_found(self) -> None:
        roots = _roots()

        for path, target in KNOWN_DIRECT_CALLERS.items():
            with self.subTest(path=path):
                self.assertIn(target, [util for _, util in roots[path]])
        self.assertGreater(
            sum(util == SYNC for includes in roots.values() for _, util in includes),
            30,
        )

    def test_every_include_passes_every_parameter_of_its_util(self) -> None:
        for path, includes in _roots().items():
            for task, target in includes:
                for via, _, _, missing in _chains(target, _scope(task), (path, target)):
                    with self.subTest(chain=" -> ".join(via)):
                        self.assertEqual(missing, [])

    def test_every_member_search_renders_along_every_include_chain(self) -> None:
        for path, includes in _roots().items():
            for task, target in includes:
                for via, util, scope, _missing in _chains(
                    target, _scope(task), (path, target)
                ):
                    if util not in READERS:
                        continue
                    for search in _reader_tasks(util):
                        with self.subTest(chain=" -> ".join(via), task=search["name"]):
                            no_log = _render(search["no_log"], scope)
                            self.assertIsInstance(no_log, bool)
                            if SEARCH not in search:
                                continue
                            attrs = _render(search[SEARCH]["attrs"], scope)
                            self.assertEqual(attrs[:4], LOGINS)
                            self.assertEqual(
                                _render(search[SEARCH]["base64_attributes"], scope),
                                attrs[4:],
                            )

    def test_a_missing_parameter_fails_the_render(self) -> None:
        search = _reader_tasks(MEMBERS)[0][SEARCH]

        with self.assertRaises(AnsibleUndefinedVariable):
            _render(search["attrs"], {})


if __name__ == "__main__":
    unittest.main()
