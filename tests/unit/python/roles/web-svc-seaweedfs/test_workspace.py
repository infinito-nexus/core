import base64
import json
import os
import unittest

from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.seaweedfs import (
    WORKSPACE_MAX_KEY,
    seaweedfs_bucket_state_files,
    seaweedfs_workspace_credentials,
    seaweedfs_workspace_slot,
)
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "web-svc-seaweedfs"
TASKS = ROLE_DIR / "tasks"
OPENBAO_DESTROY = PROJECT_ROOT / "roles/web-app-openbao/tasks/workspace/destroy.yml"
WORKSPACE_PLAYBOOK = PROJECT_ROOT / "playbook-workspace.yml"
STATE_COUNT = "workspace_state_objects"
WORKSPACE = "0b5e8c1e-6f43-4c3a-9d6b-2a1f0e9c7d11"
OTHER = "7c2d9e40-1a5b-4e8f-b3c6-90d4a2f1e5aa"
SHELL = "ansible.builtin.shell"


def _tasks(relative):
    return load_yaml_any(str(TASKS / relative))


EXPANDED = ("utils/workspace/", "utils/s3_config/")


def _flat(tasks):
    for task in tasks:
        yield task
        for section in ("block", "always", "rescue"):
            yield from _flat(task.get(section, []))
        include = str(task.get("include_tasks", ""))
        if include.startswith(EXPANDED):
            yield from _flat(_tasks(include))


def _index(tasks, prefix):
    names = [task.get("name", "") for task in tasks]
    found = [i for i, name in enumerate(names) if name.startswith(prefix)]
    if len(found) != 1:
        raise AssertionError(f"expected one task starting {prefix!r}, got {found}")
    return found[0]


def _task(tasks, prefix):
    return tasks[_index(tasks, prefix)]


def _environment():
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["basename"] = os.path.basename
    env.filters["seaweedfs_workspace_slot"] = seaweedfs_workspace_slot
    env.filters["seaweedfs_workspace_credentials"] = seaweedfs_workspace_credentials
    env.filters["b64decode"] = lambda text: base64.b64decode(text).decode()
    env.filters["from_json"] = json.loads
    env.filters["combine"] = lambda left, right: {**left, **right}
    env.filters["bool"] = to_bool
    env.filters["seaweedfs_bucket_state_files"] = seaweedfs_bucket_state_files
    return env


def _listing(*keys):
    entries = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
    return (
        "<ListBucketResult><IsTruncated>false</IsTruncated>"
        f"{entries}</ListBucketResult>\n200"
    )


def _evaluate(expression, **variables):
    return _environment().compile_expression(expression.strip())(**variables)


class TestWorkspaceApply(unittest.TestCase):
    def setUp(self):
        self.apply = list(_flat(_tasks("utils/workspace/apply.yml")))

    def _slot(self, names, maximum):
        (condition,) = _task(self.apply, "🧮 Refuse the workspace")[
            "ansible.builtin.assert"
        ]["that"]
        return _evaluate(
            condition,
            _seaweedfs_ws_records={"files": [{"path": f"/x/{n}"} for n in names]},
            WORKSPACE=WORKSPACE,
            SEAWEEDFS_WORKSPACES_MAX=maximum,
        )

    def test_apply_refuses_a_workspace_beyond_the_maximum(self):
        taken = [f"ws-{OTHER}.json"]
        self.assertTrue(self._slot(taken, "2"))
        with self.assertRaisesRegex(AnsibleFilterError, WORKSPACE_MAX_KEY):
            self._slot(taken, "1")
        self.assertTrue(self._slot([f"ws-{WORKSPACE}.json"], "1"))

    def test_the_slot_check_runs_before_anything_is_written(self):
        slot = _index(self.apply, "🧮 Refuse the workspace")
        for later in (
            "💾 Write the record",
            "🔐 Hand the keys to OpenBao",
            "📁 Create the state bucket",
            "📄 Assemble s3.json",
        ):
            with self.subTest(task=later):
                self.assertLess(slot, _index(self.apply, later))

    def test_the_maximum_comes_from_the_services_key(self):
        variables = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            variables["SEAWEEDFS_WORKSPACES_MAX"],
            "{{ lookup('config', application_id, '" + WORKSPACE_MAX_KEY + "') }}",
        )
        services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        self.assertIsInstance(services["seaweedfs"]["workspaces"]["max"], int)

    def _record(self, record_exists, openbao_rc):
        expression = _task(self.apply, "🔧 Keep the keys of the record")[
            "ansible.builtin.set_fact"
        ]["seaweedfs_ws_record"]
        stored = {"workspace": WORKSPACE, "access_key": "FILE", "secret_key": "file"}
        held = {"access_key": "BAO", "secret_key": "bao"}
        return _evaluate(
            expression.strip().removeprefix("{{").removesuffix("}}"),
            WORKSPACE=WORKSPACE,
            _seaweedfs_ws_record_stat={"stat": {"exists": record_exists}},
            _seaweedfs_ws_record_read={
                "content": base64.b64encode(json.dumps(stored).encode()).decode()
            },
            _seaweedfs_openbao_read={
                "rc": openbao_rc,
                "stdout": json.dumps({"data": {"data": held}}),
            },
        )

    def test_apply_keeps_the_keys_of_an_existing_record(self):
        self.assertEqual(self._record(True, 0)["access_key"], "FILE")
        self.assertEqual(self._record(True, 2)["access_key"], "FILE")

    def test_apply_takes_the_keys_back_from_openbao_after_a_restore(self):
        self.assertEqual(
            self._record(False, 0),
            {"workspace": WORKSPACE, "access_key": "BAO", "secret_key": "bao"},
        )

    def test_apply_generates_keys_only_when_neither_holds_them(self):
        record = self._record(False, 2)
        self.assertEqual(record["workspace"], WORKSPACE)
        self.assertNotIn(record["access_key"], ("FILE", "BAO"))

    def test_versioning_is_turned_on_for_the_bucket(self):
        task = _task(self.apply, "🗂 Turn versioning on")
        self.assertIn("?versioning", task[SHELL])
        self.assertIn("<Status>Enabled</Status>", task["args"]["stdin"])

    def test_the_record_is_private_to_root(self):
        copy = _task(self.apply, "💾 Write the record")["ansible.builtin.copy"]
        self.assertEqual((copy["owner"], copy["mode"]), ("root", "0600"))


class TestWorkspaceDestroy(unittest.TestCase):
    def setUp(self):
        self.destroy = list(_flat(_tasks("utils/workspace/destroy.yml")))

    def test_destroy_refuses_before_it_removes_anything(self):
        refuse = _index(self.destroy, "🛑 Refuse while the workspace bucket")
        for later in ("🧹 Remove the record", "🗑 Delete the workspace bucket"):
            with self.subTest(task=later):
                self.assertLess(refuse, _index(self.destroy, later))

    def test_destroy_ends_access_before_it_deletes_the_bucket(self):
        order = [
            _index(self.destroy, prefix)
            for prefix in (
                "🧹 Remove the record",
                "📄 Assemble s3.json",
                "📣 Reload the S3 identities",
                "⏳ Wait until the removed keys are refused",
                "🗑 Delete the workspace bucket",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_destroy_counts_a_missing_bucket_as_removed(self):
        for prefix in ("🛑 Refuse while", "🗑 Delete the workspace bucket"):
            with self.subTest(task=prefix):
                self.assertEqual(
                    _task(self.destroy, prefix)["when"],
                    "_seaweedfs_ws_bucket_present | bool",
                )
        listing = _task(self.destroy, "🔍 List the objects")
        self.assertIn(listing, _task(self.destroy, "🛑 Refuse while")["block"])

    def test_destroy_counts_a_missing_record_as_removed(self):
        self.assertEqual(
            _task(self.destroy, "⏳ Wait until the removed keys are refused")["when"],
            "_seaweedfs_ws_record_stat.stat.exists",
        )

    def _state_count(self, **variables):
        expression = _task(self.destroy, "📤 Hand the state files")[
            "ansible.builtin.set_fact"
        ][STATE_COUNT]
        return _evaluate(
            expression.strip().removeprefix("{{").removesuffix("}}"), **variables
        )

    def test_destroy_hands_over_the_state_files_left_in_the_bucket(self):
        for keys, expected in (
            ((), 0),
            (("SO1/1.tflock", "notes.txt"), 0),
            (("SO1/1.tfstate", "SO2/1.tfstate", "SO1/1.tflock"), 2),
        ):
            with self.subTest(keys=keys):
                count = self._state_count(
                    _seaweedfs_ws_bucket_present=True,
                    _seaweedfs_ws_objects={"stdout": _listing(*keys)},
                )
                self.assertIs(type(count), int)
                self.assertEqual(count, expected)

    def test_destroy_hands_over_no_state_for_a_missing_bucket(self):
        count = self._state_count(_seaweedfs_ws_bucket_present=False)
        self.assertIs(type(count), int)
        self.assertEqual(count, 0)

    def test_the_count_reaches_every_host_of_the_play(self):
        task = _task(self.destroy, "📤 Hand the state files")
        self.assertIs(task["delegate_facts"], True)
        self.assertEqual(task["loop"], "{{ ansible_play_hosts_all }}")
        self.assertEqual(
            task["delegate_to"], "{{ " + task["loop_control"]["loop_var"] + " }}"
        )

    def test_the_count_is_read_before_anything_is_removed(self):
        handed = _index(self.destroy, "📤 Hand the state files")
        self.assertLess(_index(self.destroy, "🔍 List the objects"), handed)
        for later in ("🧹 Remove the record", "🗑 Delete the workspace bucket"):
            with self.subTest(task=later):
                self.assertLess(handed, _index(self.destroy, later))

    def test_openbao_destroy_takes_the_count_after_this_role(self):
        guard = load_yaml_any(str(OPENBAO_DESTROY))[0]["ansible.builtin.assert"]["that"]
        env = _environment()
        for keys, accepted in ((("notes.txt",), True), (("SO1/1.tfstate",), False)):
            with self.subTest(keys=keys):
                count = self._state_count(
                    _seaweedfs_ws_bucket_present=True,
                    _seaweedfs_ws_objects={"stdout": _listing(*keys)},
                )
                self.assertEqual(
                    all(
                        env.compile_expression(condition)(
                            **{STATE_COUNT: count, "WORKSPACE": WORKSPACE}
                        )
                        for condition in guard
                    ),
                    accepted,
                )
        (play,) = load_yaml_any(str(WORKSPACE_PLAYBOOK))
        order = list(reversed(play["vars"]["workspace_roles"]))
        self.assertLess(
            order.index("web-svc-seaweedfs"), order.index("web-app-openbao")
        )


class TestWorkspaceSecrets(unittest.TestCase):
    FILES = (
        "utils/workspace/apply.yml",
        "utils/workspace/destroy.yml",
    )
    KEYED = (
        "access_key",
        "secret_key",
        "seaweedfs_ws_record",
        "_seaweedfs_openbao_login",
        "CREDENTIALS",
    )

    def _all(self):
        for relative in self.FILES:
            for task in _flat(_tasks(relative)):
                yield relative, task

    def test_no_key_reaches_an_argv(self):
        for relative, task in self._all():
            command = str(task.get(SHELL, ""))
            for needle in self.KEYED:
                with self.subTest(file=relative, task=task.get("name"), needle=needle):
                    self.assertNotIn(
                        needle, command.replace("SEAWEEDFS_S3_CREDENTIALS", "")
                    )

    def test_every_task_that_handles_keys_is_masked(self):
        for relative, task in self._all():
            handles = (
                any(
                    needle in json.dumps(task.get("args", {}))
                    or needle in json.dumps(task.get("ansible.builtin.set_fact", {}))
                    or needle in json.dumps(task.get("ansible.builtin.copy", {}))
                    for needle in self.KEYED
                )
                or "ansible.builtin.slurp" in task
            )
            if not handles:
                continue
            with self.subTest(file=relative, task=task.get("name")):
                self.assertEqual(
                    task.get("no_log"), "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"
                )


class TestWorkspaceEntry(unittest.TestCase):
    def test_the_role_runs_its_workspace_tasks_for_a_workspace_action(self):
        (task,) = [
            task
            for task in _tasks("main.yml")
            if task.get("include_tasks") == "workspace.yml"
        ]
        self.assertIn("WORKSPACE_ACTION is defined", task["when"])

    def test_the_entry_refuses_an_unknown_action(self):
        (check,) = _tasks("workspace.yml")[:1]
        self.assertIn(
            "WORKSPACE_ACTION in ['apply', 'destroy']",
            check["ansible.builtin.assert"]["that"],
        )


if __name__ == "__main__":
    unittest.main()
