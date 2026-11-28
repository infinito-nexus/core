"""Units of the sys-lock groups MUST keep the shape the lock relies on.

sys-lock treats a peer in ``start-pre`` as a waiter, never as busy. That holds
only while the lock is the sole ``ExecStartPre`` of every group unit and every
group unit is a oneshot without RemainAfterExit: a second ExecStartPre would
hide real work in ``start-pre``, a non-oneshot unit would put the manager's
DefaultTimeoutStartSec on the lock wait, and a unit that stays ``active`` after
its run would hold the ``systemctl is-active`` wait of the soft repair script.

``TimeoutStartSec`` counts the lock wait too. A lock ``--timeout`` at or above
it lets systemd kill the unit with Result=timeout before the lock gives up,
so the failure never carries the lock's own verdict naming the busy peer.

The sys-service default of ``system_service_force_linear_sync`` tests membership
in these groups, so every group unit states its choice instead of inheriting a
value that flips whenever the group lists change.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import itertools
import re
import unittest
from pathlib import Path

from jinja2 import StrictUndefined, TemplateError, UndefinedError
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.get.category_entries import get_category_entries
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
DAEMONS = PROJECT_ROOT / "group_vars" / "all" / "06_daemons.yml"
SCHEDULE = PROJECT_ROOT / "group_vars" / "all" / "07_schedule.yml"
LOCK_PREFIX = "{{ BIN_LOCK }}"
COMMAND_SEPARATOR = " ; "
OMIT = "__omit__"
DRILL_ROLE = "svc-bkp-volume-2-local"

_PREFIX_RE = re.compile(r"'([a-z0-9-]+-)'\s*\|\s*get_category_entries")
_LOCK_TIMEOUT_RE = re.compile(r'--timeout\s+"?([^"\s]+)"?')
_LOCK_TIMEOUT_VAR_RE = re.compile(r'--timeout\s+"\{\{\s*(\w+)\s*\}\}"')
_SERVICE_NAME_RE = re.compile(r"\bSYS_SERVICE_[A-Z0-9_]+\b")


def _load_sys_lock():
    path = ROLES_DIR / "sys-lock" / "files" / "python" / "sys-lock.py"
    spec = importlib.util.spec_from_file_location("sys_lock_for_lint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYS_LOCK = _load_sys_lock()


def _group_roles() -> list[str]:
    prefixes = sorted(set(_PREFIX_RE.findall(read_text(str(DAEMONS)))))
    return sorted(
        {
            role
            for prefix in prefixes
            for role in get_category_entries(prefix, roles_path=str(ROLES_DIR))
        }
    )


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


@functools.cache
def _role_files(extension: str) -> dict[tuple[str, str], list[Path]]:
    """Index the project's role files by ``(role, top-level folder)``.

    Args:
        extension: file suffix to index, such as ``.yml``.
    """
    index: dict[tuple[str, str], list[Path]] = {}
    for candidate in sorted(iter_project_files(extensions=(extension,))):
        path = Path(candidate)
        if ROLES_DIR not in path.parents:
            continue
        parts = path.relative_to(ROLES_DIR).parts
        if len(parts) > 2:
            index.setdefault((parts[0], parts[1]), []).append(path)
    return index


def _sys_service_vars(role: str):
    """Yield ``(path, vars)`` of every sys-service include in ``role``'s tasks.

    Args:
        role: role directory name under ``roles/``.
    """
    for path in _role_files(".yml").get((role, "tasks"), []):
        for task in _tasks(load_yaml_any(path, default_if_missing=[])):
            include = task.get("include_role")
            if isinstance(include, dict) and include.get("name") == "sys-service":
                yield path, task.get("vars") or {}


def _shape_violations(role: str, path: Path, unit_vars: dict) -> list[str]:
    """Return why a group unit's sys-service vars break the lock's assumptions.

    Args:
        role: role directory name, for the message.
        path: task file, for the message.
        unit_vars: the ``vars`` of the sys-service include.
    """
    where = f"{role}: {path.name}"
    found = []
    pre = unit_vars.get("system_service_tpl_exec_start_pre")
    if pre and not _lock_only(pre):
        found.append(f"{where}: ExecStartPre is not the lock alone: {pre!r}")
    unit_type = unit_vars.get("system_service_tpl_type", "oneshot")
    if unit_type != "oneshot":
        found.append(f"{where}: Type={unit_type}, not oneshot")
    remain = unit_vars.get("system_service_tpl_remain_after_exit", "")
    if str(remain).strip().lower() not in {"", "false", "no", "0"}:
        found.append(f"{where}: RemainAfterExit={remain}")
    return found


def _template_violations(role: str, path: Path, text: str) -> list[str]:
    """Return why a group unit template breaks the lock's assumptions.

    Args:
        role: role directory name, for the message.
        path: template file, for the message.
        text: template content.
    """
    where = f"{role}: {path.name}"
    lines = [line.strip() for line in text.splitlines()]
    pres = [line for line in lines if line.startswith("ExecStartPre=")]
    found = []
    if len(pres) > 1 or (
        pres and not _lock_only(pres[0].removeprefix("ExecStartPre="))
    ):
        found.append(f"{where}: ExecStartPre lines other than the lock: {pres}")
    types = [line for line in lines if line.startswith("Type=")]
    if types and types != ["Type=oneshot"]:
        found.append(f"{where}: {types}, not oneshot")
    remains = [
        line
        for line in lines
        if line.startswith("RemainAfterExit=")
        and line.removeprefix("RemainAfterExit=").lower() not in {"no", "false", "0"}
    ]
    if remains:
        found.append(f"{where}: {remains}")
    return found


def _lock_only(command) -> bool:
    return (
        isinstance(command, str)
        and command.strip().startswith(LOCK_PREFIX)
        and COMMAND_SEPARATOR not in command
    )


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if "{{" in text:
        raise ValueError(f"unrendered template reached a bool test: {text}")
    return text.lower() in {"true", "yes", "1"}


def _render_all(values: dict, env: NativeEnvironment) -> dict:
    """Resolve ``values`` against each other, rendering every template from its source each pass.

    Args:
        values: variable names and their raw values.
        env: the strict environment carrying the filters the values use.
    """
    resolved = dict(values)
    for _ in range(6):
        current = {}
        for key, value in values.items():
            current[key] = value
            if isinstance(value, str) and "{{" in value:
                with contextlib.suppress(TemplateError, TypeError, ValueError):
                    current[key] = env.from_string(value).render(resolved)
        resolved = current
    return resolved


def _debug_lookup(debug: bool):
    """Stand in for Ansible's ``lookup('debug', <role>)`` in the timeout check.

    Args:
        debug: the DEBUG value of the combination under check.

    Returns:
        A ``lookup`` callable that answers only ``debug`` and raises on any other plugin.
    """

    def lookup(plugin: str, *_args: object) -> bool:
        if plugin != "debug":
            raise UndefinedError(f"lookup('{plugin}') has no stub in this check")
        return debug

    return lookup


def _timeout_violations(role: str, unit_vars: dict, role_vars: dict) -> list[str]:
    """Return every debug/container combination whose lock outlives TimeoutStartSec.

    Args:
        role: role directory name, for the message.
        unit_vars: the ``vars`` of the sys-service include.
        role_vars: the role's ``defaults/main.yml`` overlaid by its ``vars/main.yml``.

    Raises:
        jinja2.UndefinedError, ValueError: a value the check needs does not resolve.
    """
    pre = unit_vars.get("system_service_tpl_exec_start_pre")
    start = unit_vars.get("system_service_tpl_timeout_start_sec")
    if not _lock_only(pre) or not start:
        return []
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters["bool"] = _bool
    stubs = {
        name: [] if name.startswith("SYS_SERVICE_GROUP_") else f"{name.lower()}.service"
        for name in _SERVICE_NAME_RE.findall(pre)
    }
    found = []
    for in_container, debug in itertools.product((True, False), repeat=2):
        context = _render_all(
            {
                **stubs,
                **load_yaml(SCHEDULE),
                **role_vars,
                "BIN_LOCK": "/usr/local/bin/lock",
                "DOCKER_IN_CONTAINER": in_container,
                "DEBUG": debug,
                "lookup": _debug_lookup(debug),
                "omit": OMIT,
            },
            env,
        )
        start_value = str(env.from_string(start).render(context)).strip()
        if start_value in {OMIT, ""}:
            continue
        match = _LOCK_TIMEOUT_RE.search(str(env.from_string(pre).render(context)))
        lock_seconds = SYS_LOCK.parse_time_to_seconds(
            match.group(1) if match else "1min"
        )
        start_seconds = SYS_LOCK.parse_time_to_seconds(start_value)
        if lock_seconds >= start_seconds:
            found.append(
                f"{role}: DOCKER_IN_CONTAINER={in_container} DEBUG={debug}: "
                f"lock waits {lock_seconds}s, TimeoutStartSec is {start_seconds}s"
            )
    return found


class TestLockGroupUnits(unittest.TestCase):
    def test_the_groups_are_not_empty(self):
        self.assertIn("sys-ctl-cln-bkps", _group_roles())

    def test_the_lock_is_the_only_exec_start_pre_of_a_oneshot(self):
        offenders = []
        for role in _group_roles():
            for path, unit_vars in _sys_service_vars(role):
                offenders += _shape_violations(role, path, unit_vars)
            for path in _role_files(".j2").get((role, "templates"), []):
                if path.name.endswith(".service.j2"):
                    offenders += _template_violations(role, path, read_text(str(path)))
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_the_lock_gives_up_before_systemd_kills_the_unit(self):
        offenders = []
        roles = sorted(
            {role for role, folder in _role_files(".yml") if folder == "tasks"}
        )
        for role in roles:
            role_vars = {
                **load_yaml(
                    ROLES_DIR / role / ROLE_FILE_DEFAULTS_MAIN, default_if_missing={}
                ),
                **load_yaml(
                    ROLES_DIR / role / ROLE_FILE_VARS_MAIN, default_if_missing={}
                ),
            }
            for _path, unit_vars in _sys_service_vars(role):
                offenders += _timeout_violations(role, unit_vars, role_vars)
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_every_group_unit_states_its_linear_sync(self):
        offenders = [
            f"{role}: {path.name}"
            for role in _group_roles()
            for path, unit_vars in _sys_service_vars(role)
            if "system_service_force_linear_sync" not in unit_vars
        ]
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_the_backup_drill_waits_for_the_lock_of_its_unit(self):
        lock_vars = [
            match.group(1)
            for _path, unit_vars in _sys_service_vars(DRILL_ROLE)
            if (
                match := _LOCK_TIMEOUT_VAR_RE.search(
                    str(unit_vars.get("system_service_tpl_exec_start_pre", ""))
                )
            )
        ]
        env_files = [
            path
            for path in _role_files(".j2").get((DRILL_ROLE, "templates"), [])
            if path.name == "test.env.j2"
        ]
        self.assertEqual(1, len(lock_vars), lock_vars)
        self.assertEqual(1, len(env_files), env_files)
        drill_line = next(
            line
            for line in read_text(str(env_files[0])).splitlines()
            if line.startswith("BKP_TEST_LOCK_TIMEOUT=")
        )
        self.assertIn(lock_vars[0], drill_line)

    def test_the_shape_check_flags_a_second_pre_command(self):
        self.assertTrue(
            _shape_violations(
                "demo",
                Path("main.yml"),
                {"system_service_tpl_exec_start_pre": "/bin/true"},
            )
        )
        self.assertTrue(
            _shape_violations(
                "demo",
                Path("main.yml"),
                {"system_service_tpl_exec_start_pre": "{{ BIN_LOCK }} a ; /bin/true"},
            )
        )
        self.assertTrue(
            _template_violations(
                "demo",
                Path("systemctl.service.j2"),
                "Type=simple\nExecStartPre={{ BIN_LOCK }} a\nExecStartPre=/bin/true\n",
            )
        )

    def test_the_shape_check_flags_a_unit_that_stays_active(self):
        self.assertTrue(
            _shape_violations(
                "demo",
                Path("main.yml"),
                {"system_service_tpl_remain_after_exit": True},
            )
        )
        self.assertTrue(
            _template_violations(
                "demo", Path("systemctl.service.j2"), "RemainAfterExit=yes\n"
            )
        )

    def test_the_timeout_check_flags_a_lock_outliving_the_start_timeout(self):
        self.assertTrue(
            _timeout_violations(
                "demo",
                {
                    "system_service_tpl_exec_start_pre": '{{ BIN_LOCK }} a --timeout "{{ SYS_TIMEOUT_BACKUP_SERVICES }}"',
                    "system_service_tpl_timeout_start_sec": "{{ '120s' if (DOCKER_IN_CONTAINER | bool) else omit }}",
                },
                {},
            )
        )

    def test_the_timeout_check_resolves_a_start_timeout_behind_a_role_var(self):
        self.assertTrue(
            _timeout_violations(
                "demo",
                {
                    "system_service_tpl_exec_start_pre": '{{ BIN_LOCK }} a --timeout "{{ demo_lock }}"',
                    "system_service_tpl_timeout_start_sec": "{{ '120s' if (demo_debug | bool) else omit }}",
                },
                {
                    "demo_debug": "{{ (DOCKER_IN_CONTAINER | bool) and (lookup('debug', 'demo') | bool) }}",
                    "demo_lock": "60min",
                },
            )
        )

    def test_the_timeout_check_fails_loudly_on_an_unresolved_value(self):
        with self.assertRaises(UndefinedError):
            _timeout_violations(
                "demo",
                {
                    "system_service_tpl_exec_start_pre": '{{ BIN_LOCK }} a --timeout "{{ demo_missing }}"',
                    "system_service_tpl_timeout_start_sec": "120s",
                },
                {},
            )


if __name__ == "__main__":
    unittest.main()
