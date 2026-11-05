from __future__ import annotations

import base64
import importlib.util
import json
import re
import shlex
import sys
import unittest

from ansible.plugins.filter.core import b64encode, to_json
from ansible.template import Templar, trust_as_template
from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles/web-app-nextcloud"
STAGES = ROLE / "tasks/02_manager_ops/06_plugin"
INSTALL = STAGES / "02_install.yml"
ENABLE = STAGES / "03_enable.yml"
CONFIGURE = STAGES / "04_configure.yml"

FRESH = {"rc": 0, "stdout": "deck 1.18.6 installed\ndeck enabled", "stderr": ""}
KEPT_DISABLED = {"rc": 0, "stdout": "deck 1.18.6 installed", "stderr": ""}
PLACED = {"rc": 1, "stdout": "recognize already installed", "stderr": ""}
INCOMPATIBLE = {
    "rc": 1,
    "stdout": "deck is not compatible with this version of the server",
    "stderr": "",
}
UNAVAILABLE = {
    "rc": 1,
    "stdout": "Error: Could not download app deck, it was not found on the appstore",
    "stderr": "",
}


def _filters(rel_path: str, name: str) -> dict:
    spec = importlib.util.spec_from_file_location(name, str(ROLE / rel_path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


ENV = Environment(autoescape=True)
ENV.filters.update(
    _filters("filter_plugins/nextcloud_install.py", "nextcloud_install_stages")
)
ENV.filters.update(
    _filters("filter_plugins/nextcloud_plugin_config.py", "nextcloud_config_stages")
)
ENV.filters.update({"to_json": to_json, "b64encode": b64encode})


def _tasks(path) -> list[dict]:
    return load_yaml_any(str(path), default_if_missing=[])


def _runs(task: dict, install_result: dict) -> bool:
    conditions = task["when"] if isinstance(task["when"], list) else [task["when"]]
    return all(
        bool(ENV.compile_expression(condition)(install_result=install_result))
        for condition in conditions
    )


def _queue(path) -> dict:
    return next(task for task in _tasks(path) if "Queue" in task.get("name", ""))


class TestEnableStageAfterInstall(unittest.TestCase):
    def setUp(self):
        tasks = _tasks(INSTALL)
        self.enable_index = next(
            i
            for i, task in enumerate(tasks)
            if task.get("include_tasks") == "03_enable.yml"
        )
        self.enable = tasks[self.enable_index]
        self.queue_index = next(
            i for i, task in enumerate(tasks) if "Queue" in task.get("name", "")
        )
        self.queue = tasks[self.queue_index]

    def test_an_install_that_enabled_the_plugin_skips_the_enable_stage(self):
        self.assertFalse(_runs(self.enable, FRESH))
        self.assertTrue(_runs(self.queue, FRESH))

    def test_an_install_that_left_the_plugin_off_runs_the_enable_stage(self):
        for result in (PLACED, KEPT_DISABLED):
            with self.subTest(stdout=result["stdout"]):
                self.assertTrue(_runs(self.enable, result))
                self.assertFalse(_runs(self.queue, result))

    def test_a_plugin_that_cannot_run_is_neither_enabled_nor_queued(self):
        for result in (INCOMPATIBLE, UNAVAILABLE):
            with self.subTest(stdout=result["stdout"]):
                self.assertFalse(_runs(self.enable, result))
                self.assertFalse(_runs(self.queue, result))

    def test_the_direct_queue_appends_like_the_enable_stage(self):
        self.assertEqual(
            self.queue["ansible.builtin.set_fact"],
            _queue(ENABLE)["ansible.builtin.set_fact"],
        )

    def test_the_queue_keeps_the_install_loop_order(self):
        self.assertEqual(self.queue_index, self.enable_index + 1)


OCC = "/var/www/html/occ"
ENTRIES = [
    {"appid": "user_ldap", "configkey": "s01ldap_port", "type": None, "value": "389"},
    {
        "appid": "spreed",
        "configkey": "stun_servers",
        "type": "array",
        "value": '["coturn.example:3481"]',
    },
    {
        "appid": "user_ldap",
        "configkey": "s01ldap_group_filter",
        "type": None,
        "value": "(&(|(objectclass=groupOfNames))(cn=it's $HOME `x`))",
    },
    {"appid": "richdocuments", "configkey": "wopi_url", "type": None, "value": ""},
    {
        "appid": "user_ldap",
        "configkey": "s01ldap_groupfilter_objectclass",
        "type": None,
        "value": "groupOfUniqueNames\nposixGroup",
    },
    {"appid": "whiteboard", "configkey": "jwt_secret_key", "type": None, "value": "é"},
]


def _batch(pending: list[dict]) -> list[dict]:
    task = next(
        task
        for task in _tasks(CONFIGURE)
        if "Set the pending plugin configuration" in task.get("name", "")
    )
    stdin = task["ansible.builtin.shell"]["stdin"]
    match = re.fullmatch(
        r"<\?php \$occBatch = '\{\{(.+?)\}\}'; \?>"
        r"\{\{ lookup\('file', 'php/utils/occ_batch\.php'\) \}\}",
        stdin.strip(),
    )
    assert match, stdin
    payload = ENV.compile_expression(match.group(1))(
        nextcloud_plugin_config_pending=pending
    )
    return json.loads(base64.b64decode(payload, validate=True))


PREVIOUS_SHELL_LINE = (
    "{{ occ | quote }} config:app:set {{ item.appid | quote }} "
    "{{ item.configkey | quote }}"
    "{{ (' --no-interaction --type=' ~ item.type) if item.type is not none else '' }}"
    " --value {{ item.value | quote }}"
)


def _previous_argv(item: dict) -> list[str]:
    """The argv the former ``sh -s`` line handed to occ for one pending entry.

    Args:
      item: one ``nextcloud_plugin_config_pending`` entry.
    """
    line = Templar(variables={"occ": OCC, "item": item}).template(
        trust_as_template(PREVIOUS_SHELL_LINE)
    )
    return shlex.split(line)


class TestConfigureBatch(unittest.TestCase):
    def test_every_pending_entry_reaches_the_runner_in_order(self):
        self.assertEqual(
            [call["label"] for call in _batch(ENTRIES)],
            [f"{item['appid']}/{item['configkey']}" for item in ENTRIES],
        )

    def test_each_call_hands_occ_the_argv_of_the_former_shell_line(self):
        for item, call in zip(ENTRIES, _batch(ENTRIES), strict=True):
            with self.subTest(key=item["configkey"]):
                self.assertEqual([OCC, *call["argv"]], _previous_argv(item))

    def test_an_untyped_entry_keeps_the_stored_type(self):
        argv = _batch(ENTRIES[:1])[0]["argv"]
        self.assertNotIn("--no-interaction", argv)
        self.assertFalse(any(arg.startswith("--type") for arg in argv))


if __name__ == "__main__":
    unittest.main()
