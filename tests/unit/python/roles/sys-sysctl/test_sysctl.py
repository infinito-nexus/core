"""Contract of sys-sysctl: the kernel.core_pattern default per distro family,
the container rule that keeps host-global keys out of a container, the drop-in
per owner and its directory, the migrated consumers and the idempotence of the
real module. Each
contract carries a negative control that proves its checker can fail."""

import itertools
import json
import posixpath
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ansible_collections.ansible.posix as ansible_posix
from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, StrictUndefined

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ROLES = PROJECT_ROOT / "roles"
ROLE = ROLES / "sys-sysctl"
CORE_KEY = "kernel.core_pattern"
SYSCTL_MODULES = ("sysctl", "ansible.posix.sysctl")
INCLUDE_MODULES = ("include_role", "ansible.builtin.include_role")
VENDOR_DROPINS = ("10-coredump-debian.conf", "50-coredump.conf")
CORENAME_MAX_SIZE = 128
IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
PROBED_HANDLER = {
    "Archlinux": "/usr/lib/systemd/systemd-coredump",
    "Debian": "/usr/lib/systemd/systemd-coredump",
    "RedHat": "/usr/lib/systemd/systemd-coredump",
}
NAMESPACED_KEYS = (
    "net.ipv4.ip_forward",
    "net.ipv4.conf.all.rp_filter",
    "kernel.shmmax",
    "kernel.shm_rmid_forced",
    "kernel.msgmnb",
    "kernel.msg_next_id",
    "kernel.sem",
    "kernel.sem_next_id",
    "fs.mqueue.msg_max",
    "kernel.hostname",
    "kernel.domainname",
)
GLOBAL_KEYS = (
    "kernel.core_pattern",
    "vm.max_map_count",
    "fs.inotify.max_user_watches",
    "kernel.pid_max",
    "kernel.semx",
    "kernel.hostname_extra",
    "network.foo",
)
OLD_CONSUMERS = {
    "web-app-wazuh": {
        "parameters": {"vm.max_map_count": "262144"},
        "file": "/etc/sysctl.d/99-wazuh-indexer.conf",
        "in_container": {},
    },
    "svc-runner": {
        "parameters": {
            "fs.inotify.max_user_instances": "8192",
            "fs.inotify.max_user_watches": "524288",
            "fs.inotify.max_queued_events": "65536",
        },
        "file": "/etc/sysctl.d/99-runner.conf",
        "in_container": {},
    },
    "svc-net-wireguard": {
        "parameters": {"net.ipv4.ip_forward": "1"},
        "file": "/etc/sysctl.conf",
        "in_container": {"net.ipv4.ip_forward": "1"},
    },
}
ADDED_PARAMETERS = {
    "svc-runner": {"vm.max_map_count": "262144"},
}
MAP_COUNT_KEY = "vm.max_map_count"
MAP_COUNT_FLOOR = 262144
SEARCH_ENGINE_CONSUMERS = {
    "svc-db-elasticsearch": "/etc/sysctl.d/99-elasticsearch.conf",
    "web-app-zammad": "/etc/sysctl.d/99-zammad.conf",
    "web-app-magento": "/etc/sysctl.d/99-magento.conf",
    "web-app-shopware": "/etc/sysctl.d/99-shopware.conf",
}
CONSUMER_PREFIX = {
    "web-app-wazuh": "WAZUH",
    "svc-runner": "RUNNER",
    "svc-net-wireguard": "WIREGUARD",
    "svc-db-elasticsearch": "ELASTICSEARCH",
    "web-app-zammad": "ZAMMAD",
    "web-app-magento": "MAGENTO",
    "web-app-shopware": "SHOPWARE",
}
STACK_STAGE = "tasks/utils/stack/stage.yml"
CONSUMER_TASKS = {"web-app-magento": STACK_STAGE, "web-app-shopware": STACK_STAGE}
HANDED = {
    "sys_sysctl_owner": "OWNER",
    "sys_sysctl_parameters": "PARAMETERS",
    "sys_sysctl_retired_files": "RETIRED_FILES",
}
SYSCTL_MODULE = (
    Path(next(iter(ansible_posix.__path__))) / "plugins" / "modules" / "sysctl.py"
)


def _env():
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders ansible expressions, not markup
    env.filters["path_join"] = lambda parts: posixpath.join(*parts)
    env.filters["dirname"] = posixpath.dirname
    env.filters["bool"] = boolean
    env.filters["entity_name"] = entity_name
    env.filters["dict2items"] = lambda d: [{"key": k, "value": v} for k, v in d.items()]
    env.filters["items2dict"] = lambda items: {i["key"]: i["value"] for i in items}
    env.filters["product"] = lambda a, b: list(itertools.product(a, b))
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    return env


def _role_vars():
    paths = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/05_paths.yml"))
    merged = {"DIR_VAR_LIB": paths["DIR_VAR_LIB"]}
    merged.update(load_yaml_any(str(ROLE / ROLE_FILE_DEFAULTS_MAIN)))
    merged.update(load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN)))
    return merged


def _render(value, context, env):
    if isinstance(value, str) and "{{" in value:
        expression = value.strip()
        if expression.startswith("{{") and expression.endswith("}}"):
            return env.compile_expression(expression[2:-2])(**context)
        return env.from_string(value).render(**context)
    if isinstance(value, dict):
        return {k: _render(v, context, env) for k, v in value.items()}
    return value


def _resolve(overrides=None, handler_exists=True, in_container=False):
    env = _env()
    context = dict(_role_vars())
    context.update(
        DOCKER_IN_CONTAINER=in_container,
        sys_sysctl_core_handler={"stat": {"exists": handler_exists}},
    )
    context.update(overrides or {})
    pending, done = dict(context), {}
    while pending:
        ready = [
            key
            for key, value in pending.items()
            if not (set(IDENTIFIER.findall(json.dumps(value))) & set(pending)) - {key}
        ]
        if not ready:
            raise AssertionError(f"unresolvable variables: {sorted(pending)}")
        for key in ready:
            done[key] = _render(pending.pop(key), done, env)
    return done


def _writable_keys(parameters, in_container):
    resolved = _resolve(
        {"sys_sysctl_parameters": parameters}, in_container=in_container
    )
    return {item["key"] for item in resolved["sys_sysctl_writable"]}


def _tasks():
    return load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))


def _module_name(task, names):
    return next((name for name in names if name in task), None)


def _sorts_last(dropin):
    return all(posixpath.basename(dropin) > vendor for vendor in VENDOR_DROPINS)


def _calls_sysctl_module(text):
    return (
        re.search(r"^\s*(ansible\.posix\.)?sysctl:\s*$", text, re.MULTILINE) is not None
    )


def _map_count_floor_met(applied):
    return int(applied.get(MAP_COUNT_KEY, 0)) >= MAP_COUNT_FLOOR


def _required_by_roles():
    entry = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["sysctl"]["required_by"]
    return {mode: set(entry[mode]["roles"]) for mode in ("compose", "swarm")}


def _undeclared(declared):
    return sorted(set(CONSUMER_PREFIX) - set(declared))


def _consumer_vars(role):
    return load_yaml_any(str(ROLES / role / ROLE_FILE_VARS_MAIN))


def _sysctl_includes(role):
    """
    Args:
        role: a consumer role of sys-sysctl.

    Returns:
        The vars of every task in its consumer task file that includes sys-sysctl.
    """
    pending = list(
        load_yaml_any(str(ROLES / role / CONSUMER_TASKS.get(role, "tasks/00_core.yml")))
    )
    found = []
    while pending:
        task = pending.pop(0)
        for key in ("block", "rescue", "always"):
            pending.extend(task.get(key) or [])
        include = task.get("ansible.builtin.include_role") or task.get("include_role")
        if isinstance(include, dict) and include.get("name") == "sys-sysctl":
            found.append(task.get("vars", {}))
    return found


def _consumer_effect(role, in_container):
    raw = _consumer_vars(role)
    prefix = CONSUMER_PREFIX[role]
    env = _env()
    owner = env.from_string(raw[f"{prefix}_SYSCTL_OWNER"]).render(
        application_id=raw["application_id"]
    )
    parameters = raw[f"{prefix}_SYSCTL_PARAMETERS"]
    retired = raw.get(f"{prefix}_SYSCTL_RETIRED_FILES", [])
    resolved = _resolve(
        {
            "sys_sysctl_owner": owner,
            "sys_sysctl_parameters": parameters,
            "sys_sysctl_retired_files": retired,
        },
        in_container=in_container,
    )
    applied = {i["key"]: i["value"] for i in resolved["sys_sysctl_writable"]}
    return parameters, resolved["sys_sysctl_file"], retired, applied


def _differences(role, old):
    parameters, dropin, retired, applied_host = _consumer_effect(role, False)
    _p, _d, _r, applied_container = _consumer_effect(role, True)
    issues = []
    if parameters != old["parameters"] or applied_host != old["parameters"]:
        issues.append("host values")
    if applied_container != old["in_container"]:
        issues.append("container behaviour")
    if dropin != old["file"] and old["file"] not in retired:
        issues.append("old file neither reused nor retired")
    return issues


def _run_sysctl_module(sysctl_file, value, state="present", name=CORE_KEY):
    args = {
        "name": name,
        "sysctl_file": str(sysctl_file),
        "state": state,
        "sysctl_set": False,
        "reload": False,
    }
    if state == "present":
        args["value"] = value
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump({"ANSIBLE_MODULE_ARGS": args}, handle)
    result = subprocess.run(
        [sys.executable, str(SYSCTL_MODULE), handle.name],
        capture_output=True,
        text=True,
        check=False,
    )
    Path(handle.name).unlink()
    if not result.stdout.strip():
        return {"failed": True, "msg": result.stderr}
    return json.loads(result.stdout)


def _replay(tasks, context, root):
    """Replays the directory and persist steps of ``tasks`` in their order.

    Args:
        tasks: role tasks as loaded from tasks/main.yml.
        context: resolved role variables the tasks render against.
        root: temporary directory every created path must stay inside.

    Returns:
        The result of every persist call, in order.
    """
    env = _env()
    results = []
    for task in tasks:
        when = task.get("when")
        if when and not env.compile_expression(when)(**context):
            continue
        directory = task.get("ansible.builtin.file", {})
        if directory.get("state") == "directory":
            path = Path(_render(directory["path"], context, env))
            if not path.is_relative_to(root):
                raise AssertionError(f"{path} escapes {root}")
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(int(_render(directory["mode"], context, env), 8))
        persist = task.get("ansible.posix.sysctl", {})
        if persist.get("state") == "present":
            dropin = _render(persist["sysctl_file"], context, env)
            results.extend(
                _run_sysctl_module(dropin, item["value"], name=item["key"])
                for item in _render(task["loop"], context, env)
            )
    return results


def _hub_context(root):
    return _resolve(
        {
            "sys_sysctl_owner": "wireguard",
            "sys_sysctl_parameters": {"net.ipv4.ip_forward": "1"},
            "sys_sysctl_file": str(root / "etc/sysctl.d/99-wireguard.conf"),
        },
        in_container=True,
    )


class TestCorePatternDefault(unittest.TestCase):
    def test_families_match_the_probed_handler(self):
        families = {
            distro["family"]
            for distro in load_yaml_any(str(PROJECT_ROOT / "meta/distros.yml"))[
                "distros"
            ].values()
        }
        self.assertEqual(families, set(PROBED_HANDLER))
        for family in sorted(families):
            with self.subTest(family=family):
                self.assertEqual(
                    _role_vars()["SYS_SYSCTL_CORE_HANDLER"], PROBED_HANDLER[family]
                )

    def test_pipe_where_the_handler_exists(self):
        self.assertEqual(
            _resolve(handler_exists=True)["SYS_SYSCTL_PARAMETERS"][CORE_KEY],
            "|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h %d %F",
        )

    def test_file_in_the_dedicated_directory_elsewhere(self):
        resolved = _resolve(handler_exists=False)
        pattern = resolved["SYS_SYSCTL_PARAMETERS"][CORE_KEY]
        self.assertEqual(posixpath.dirname(pattern), resolved["SYS_SYSCTL_CORE_DIR"])
        self.assertTrue(posixpath.isabs(pattern))

    def test_both_defaults_fit_the_kernel_limit(self):
        for exists in (True, False):
            with self.subTest(handler_exists=exists):
                pattern = _resolve(handler_exists=exists)["SYS_SYSCTL_PARAMETERS"][
                    CORE_KEY
                ]
                self.assertLess(len(pattern.encode()), CORENAME_MAX_SIZE)

    def test_negative_control_relative_patterns_land_in_the_cwd(self):
        for pattern in ("core", "core.%e.%p"):
            with self.subTest(pattern=pattern):
                self.assertFalse(pattern.startswith("|") or posixpath.isabs(pattern))

    def test_constructor_applies_the_option_under_the_host_owner(self):
        resolved = _resolve()
        self.assertEqual(resolved["sys_sysctl_owner"], "host")
        self.assertEqual(
            resolved["sys_sysctl_parameters"], resolved["SYS_SYSCTL_PARAMETERS"]
        )
        self.assertEqual(resolved["sys_sysctl_file"], "/etc/sysctl.d/99-host.conf")


class TestContainerRule(unittest.TestCase):
    def test_namespaced_keys_are_written_in_a_container(self):
        for key in NAMESPACED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(_writable_keys({key: "1"}, True), {key})

    def test_negative_control_global_keys_are_skipped_in_a_container(self):
        for key in GLOBAL_KEYS:
            with self.subTest(key=key):
                self.assertEqual(_writable_keys({key: "1"}, True), set())

    def test_every_key_is_written_on_a_host(self):
        keys = set(NAMESPACED_KEYS + GLOBAL_KEYS)
        self.assertEqual(_writable_keys(dict.fromkeys(keys, "1"), False), keys)

    def test_skipped_keys_are_the_complement(self):
        parameters = {"net.ipv4.ip_forward": "1", "vm.max_map_count": "262144"}
        resolved = _resolve({"sys_sysctl_parameters": parameters}, in_container=True)
        self.assertEqual(
            [i["key"] for i in resolved["sys_sysctl_skipped"]], ["vm.max_map_count"]
        )

    def test_every_write_loops_only_the_writable_keys(self):
        writes = [t for t in _tasks() if _module_name(t, SYSCTL_MODULES)]
        self.assertEqual(len(writes), 2)
        for task in writes:
            with self.subTest(task=task["name"]):
                self.assertIn("sys_sysctl_writable", task["loop"])
        skip = [t for t in _tasks() if "sys_sysctl_skipped" in str(t.get("loop", ""))]
        self.assertEqual(len(skip), 1)
        self.assertIn("ansible.builtin.debug", skip[0])

    def test_negative_control_a_loop_over_all_items_is_flagged(self):
        task = {"ansible.posix.sysctl": {}, "loop": "{{ sys_sysctl_items }}"}
        self.assertNotIn("sys_sysctl_writable", task["loop"])


class TestDropIn(unittest.TestCase):
    def test_one_dropin_per_owner_sorting_after_the_vendor_files(self):
        for owner in ("host", "runner", "wazuh-indexer", "wireguard"):
            with self.subTest(owner=owner):
                dropin = _resolve({"sys_sysctl_owner": owner})["sys_sysctl_file"]
                self.assertEqual(dropin, f"/etc/sysctl.d/99-{owner}.conf")
                self.assertTrue(_sorts_last(dropin))

    def test_negative_control_a_low_number_is_flagged(self):
        self.assertFalse(_sorts_last("/etc/sysctl.d/20-host.conf"))

    def test_owner_sysctl_is_refused(self):
        raw = _role_vars()
        self.assertIsNotNone(re.match(raw["SYS_SYSCTL_OWNER_PATTERN"], "wazuh-indexer"))
        self.assertIn("sysctl", raw["SYS_SYSCTL_OWNER_RESERVED"])
        self.assertIsNone(re.match(raw["SYS_SYSCTL_OWNER_PATTERN"], "../etc"))

    def test_retired_files_are_cleaned_only_after_the_apply(self):
        names = [t["name"] for t in _tasks()]
        apply = next(
            i
            for i, t in enumerate(_tasks())
            if t.get("ansible.posix.sysctl", {}).get("state") == "present"
        )
        retire = next(
            i
            for i, t in enumerate(_tasks())
            if t.get("ansible.posix.sysctl", {}).get("state") == "absent"
        )
        self.assertLess(apply, retire, names)
        self.assertFalse(_tasks()[retire]["ansible.posix.sysctl"]["reload"])


class TestDropInDirectory(unittest.TestCase):
    def _first_write(self, tasks):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _hub_context(root)
            results = _replay(tasks, context, root)
            dropin = Path(context["sys_sysctl_file"])
            written = read_text(str(dropin)) if dropin.exists() else None
        return results, written

    def test_the_first_write_creates_the_missing_dropin_directory(self):
        results, written = self._first_write(_tasks())
        self.assertEqual([result.get("failed", False) for result in results], [False])
        self.assertEqual(written.splitlines(), ["net.ipv4.ip_forward=1"])

    def test_negative_control_without_the_directory_step_the_write_fails(self):
        tasks = [task for task in _tasks() if "ansible.builtin.file" not in task]
        results, written = self._first_write(tasks)
        self.assertTrue(results[0]["failed"])
        self.assertIn("No such file or directory", results[0]["msg"])
        self.assertIn(".ansible_m_sysctl_", results[0]["msg"])
        self.assertIsNone(written)

    def test_negative_control_a_directory_step_after_the_write_is_too_late(self):
        tasks = _tasks()
        late = [t for t in tasks if "ansible.builtin.file" not in t] + [
            t for t in tasks if "ansible.builtin.file" in t
        ]
        results, written = self._first_write(late)
        self.assertTrue(results[0]["failed"])
        self.assertIsNone(written)

    def test_nothing_is_created_when_no_key_is_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _resolve(
                {
                    "sys_sysctl_parameters": {"vm.max_map_count": "262144"},
                    "sys_sysctl_file": str(root / "etc/sysctl.d/99-host.conf"),
                },
                in_container=True,
            )
            self.assertEqual(_replay(_tasks(), context, root), [])
            self.assertEqual(list(root.iterdir()), [])


class TestConsumers(unittest.TestCase):
    def test_effective_parameters_match_the_old_tasks(self):
        for role, old in OLD_CONSUMERS.items():
            expected = dict(
                old, parameters={**old["parameters"], **ADDED_PARAMETERS.get(role, {})}
            )
            with self.subTest(role=role):
                self.assertEqual(_differences(role, expected), [])

    def test_runner_host_keeps_the_map_count_the_container_leak_provided(self):
        _parameters, dropin, _retired, applied_host = _consumer_effect(
            "svc-runner", False
        )
        _p, _d, _r, applied_container = _consumer_effect("svc-runner", True)
        self.assertEqual(applied_host["vm.max_map_count"], "262144")
        self.assertEqual(dropin, "/etc/sysctl.d/99-runner.conf")
        self.assertNotIn("vm.max_map_count", applied_container)

    def test_negative_control_the_old_runner_set_lacks_the_map_count(self):
        self.assertNotIn("vm.max_map_count", OLD_CONSUMERS["svc-runner"]["parameters"])
        self.assertIn(
            "host values", _differences("svc-runner", OLD_CONSUMERS["svc-runner"])
        )

    def test_negative_control_a_drifted_value_is_flagged(self):
        old = dict(
            OLD_CONSUMERS["web-app-wazuh"], parameters={"vm.max_map_count": "65530"}
        )
        self.assertIn("host values", _differences("web-app-wazuh", old))

    def test_negative_control_a_changed_container_behaviour_is_flagged(self):
        old = dict(OLD_CONSUMERS["svc-net-wireguard"], in_container={})
        self.assertIn("container behaviour", _differences("svc-net-wireguard", old))

    def test_consumers_hand_their_parameters_to_sys_sysctl(self):
        env = _env()
        for role, prefix in CONSUMER_PREFIX.items():
            raw = _consumer_vars(role)
            with self.subTest(role=role):
                (handed,) = _sysctl_includes(role)
                self.assertLessEqual(
                    {"sys_sysctl_owner", "sys_sysctl_parameters"}, set(handed)
                )
                self.assertEqual(
                    {key: _render(value, raw, env) for key, value in handed.items()},
                    {key: raw[f"{prefix}_SYSCTL_{HANDED[key]}"] for key in handed},
                )

    def test_search_engines_raise_the_map_count_in_their_own_dropin(self):
        for role, expected_dropin in SEARCH_ENGINE_CONSUMERS.items():
            parameters, dropin, retired, applied_host = _consumer_effect(role, False)
            _p, _d, _r, applied_container = _consumer_effect(role, True)
            with self.subTest(role=role):
                self.assertEqual(parameters, {MAP_COUNT_KEY: str(MAP_COUNT_FLOOR)})
                self.assertTrue(_map_count_floor_met(applied_host))
                self.assertEqual(dropin, expected_dropin)
                self.assertEqual(retired, [])
                self.assertEqual(applied_container, {})

    def test_negative_control_a_missing_or_low_map_count_is_flagged(self):
        self.assertFalse(_map_count_floor_met({}))
        self.assertFalse(_map_count_floor_met({MAP_COUNT_KEY: "65530"}))

    def test_every_consumer_is_declared_in_required_by(self):
        declared = _required_by_roles()
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(_undeclared(declared[mode]), [])

    def test_negative_control_an_undeclared_consumer_is_flagged(self):
        partial = set(CONSUMER_PREFIX) - {"web-app-shopware"}
        self.assertEqual(_undeclared(partial), ["web-app-shopware"])

    def test_no_role_but_sys_sysctl_calls_the_sysctl_module(self):  # nocheck: test.text-presence -- repository-wide lint over every role task file  # fmt: skip
        role_files = [
            rel
            for rel in (
                Path(path).resolve().relative_to(PROJECT_ROOT)
                for path in iter_project_files(extensions=(".yml",))
            )
            if rel.parts[0] == "roles"
        ]
        self.assertTrue(any(rel.parts[1] == "sys-sysctl" for rel in role_files))
        offenders = [
            str(rel)
            for rel in role_files
            if rel.parts[1] != "sys-sysctl"
            and _calls_sysctl_module(read_text(str(PROJECT_ROOT / rel)))
        ]
        self.assertEqual(offenders, [])
        self.assertTrue(
            any(
                _calls_sysctl_module(read_text(str(PROJECT_ROOT / rel)))
                for rel in role_files
                if rel.parts[1] == "sys-sysctl"
            )
        )

    def test_negative_control_a_direct_sysctl_call_is_detected(self):
        self.assertTrue(_calls_sysctl_module("- name: x\n  ansible.posix.sysctl:\n"))
        self.assertFalse(
            _calls_sysctl_module("- include_role:\n    name: sys-sysctl\n")
        )


class TestIdempotence(unittest.TestCase):
    def test_second_run_reports_no_change(self):
        pattern = _resolve()["SYS_SYSCTL_PARAMETERS"][CORE_KEY]
        with tempfile.TemporaryDirectory() as tmp:
            dropin = Path(tmp) / "99-host.conf"
            self.assertTrue(_run_sysctl_module(dropin, pattern)["changed"])
            self.assertFalse(_run_sysctl_module(dropin, pattern)["changed"])
            self.assertEqual(
                read_text(str(dropin)).splitlines(), [f"{CORE_KEY}={pattern}"]
            )

    def test_negative_control_a_drifted_value_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            dropin = Path(tmp) / "99-host.conf"
            _run_sysctl_module(dropin, "|/a")
            self.assertTrue(_run_sysctl_module(dropin, "/b")["changed"])

    def test_retiring_drops_the_old_line_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            retired = Path(tmp) / "sysctl.conf"
            _run_sysctl_module(retired, "1", name="net.ipv4.ip_forward")
            first = _run_sysctl_module(retired, None, "absent", "net.ipv4.ip_forward")
            second = _run_sysctl_module(retired, None, "absent", "net.ipv4.ip_forward")
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertNotIn("net.ipv4.ip_forward", read_text(str(retired)) + "\n")

    def test_retiring_a_missing_file_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "sysctl.conf"
            result = _run_sysctl_module(missing, None, "absent", "net.ipv4.ip_forward")
            self.assertFalse(result["changed"])
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
