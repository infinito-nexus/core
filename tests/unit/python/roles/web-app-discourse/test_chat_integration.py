from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-discourse"
TASKS = ROLE / "tasks" / "addons" / "discourse-chat-integration.yml"
STACK_HOST = ROLE / "tasks" / "04_stack_host.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN
APPLICATION_ID = "web-app-discourse"

PLUGIN = "chat_integration_enabled"
MATRIX = "chat_integration_matrix_enabled"
MATTERMOST = "chat_integration_mattermost_enabled"

STUBS = """
require 'json'

class SiteSetting
  def self.values
    @values ||= JSON.parse(File.read(ENV.fetch('STUB_STORE')))
  end

  def self.method_missing(name, *args)
    key = name.to_s.delete_suffix('=')
    return super unless values.key?(key)
    return values[key] unless name.to_s.end_with?('=')

    values[key] = args.first unless ENV.fetch('STUB_DROP_WRITES') == 'true'
    File.write(ENV.fetch('STUB_STORE'), JSON.generate(values))
  end

  def self.respond_to_missing?(name, include_private = false)
    values.key?(name.to_s.delete_suffix('=')) || super
  end
end

eval($stdin.read, TOPLEVEL_BINDING, 'stdin')
"""


def _config_lookup(values: dict[str, object]):
    """Build a ``lookup('config', application_id, <key>)`` stub.

    Args:
        values: the value each config key resolves to

    Returns:
        a callable standing in for Ansible's ``lookup``
    """

    def lookup(kind: str, application_id: str, key: str) -> object:
        assert (kind, application_id) == ("config", APPLICATION_ID)
        return values[key]

    return lookup


def _settings(matrix: bool, mattermost: bool) -> list[str]:
    """Render ``DISCOURSE_CHAT_INTEGRATION_SETTINGS`` for one round.

    Args:
        matrix: value of ``services.matrix.enabled``
        mattermost: value of ``services.mattermost.enabled``

    Returns:
        the site settings the addon task switches on
    """
    lookup = _config_lookup(
        {
            "services.matrix.enabled": matrix,
            "services.mattermost.enabled": mattermost,
        }
    )
    environment = NativeEnvironment(undefined=StrictUndefined)
    environment.filters["bool"] = bool
    expression = load_yaml_any(str(VARS))["DISCOURSE_CHAT_INTEGRATION_SETTINGS"]
    return environment.from_string(expression).render(
        lookup=lookup, application_id=APPLICATION_ID
    )


def _task(module: str, position: int = 0) -> dict:
    """Return one task of the addon task file by its module.

    Args:
        module: fully qualified module key, e.g. ``ansible.builtin.command``
        position: index among the tasks that use ``module``

    Returns:
        the task mapping as Ansible loads it
    """
    return [task for task in load_yaml_any(str(TASKS)) if module in task][position]


def _render(template: str, **variables: object) -> object:
    """Render a templated task value to its native type, as Ansible does.

    Args:
        template: the value with its ``{{ }}`` delimiters, e.g. ``loop``
        variables: the names the template reads

    Returns:
        the native value the template yields
    """
    environment = NativeEnvironment(undefined=StrictUndefined)
    return environment.from_string(template).render(**variables)


def _evaluate(expression: str, **variables: object) -> object:
    """Evaluate a bare Jinja expression such as ``changed_when`` or ``that``.

    Args:
        expression: the expression without ``{{ }}``
        variables: the names the expression reads

    Returns:
        the native value the expression yields
    """
    return _render("{{ " + expression + " }}", **variables)


def _ruby_code(task: dict, settings: list[str]) -> str:
    """Render the code argument a ``rails r`` task passes.

    Args:
        task: a ``container exec … rails r <code>`` task of the addon
        settings: value of ``DISCOURSE_CHAT_INTEGRATION_SETTINGS``

    Returns:
        the Ruby program ``rails r`` evaluates
    """
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[-3:-1] == ["rails", "r"], argv
    environment = Environment(
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    context = {"DISCOURSE_CHAT_INTEGRATION_SETTINGS": settings}

    def lookup(kind: str, relative: str) -> str:
        assert kind == "template", kind
        source = read_text(str(ROLE / "templates" / relative))
        return environment.from_string(source).render(context)

    return environment.from_string(argv[-1]).render(lookup=lookup, **context)


@unittest.skipUnless(shutil.which("ruby"), "needs a ruby interpreter")
class TestChatIntegrationTask(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "site_settings.json"

    def _seed(self, values: dict[str, bool]) -> None:
        self.store.write_text(json.dumps(values), encoding="utf-8")

    def _stored(self) -> dict[str, bool]:
        text = self.store.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return json.loads(text)

    def _rails_r(
        self, task: dict, settings: list[str], drop_writes: bool = False
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ruby", "-e", STUBS],
            input=_ruby_code(task, settings),
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ["PATH"],
                "STUB_STORE": str(self.store),
                "STUB_DROP_WRITES": str(drop_writes).lower(),
            },
            check=False,
        )

    def _write(
        self, settings: list[str], drop_writes: bool = False
    ) -> tuple[subprocess.CompletedProcess, bool]:
        task = _task("ansible.builtin.command", 0)
        result = self._rails_r(task, settings, drop_writes)
        changed = _evaluate(
            task["changed_when"],
            **{task["register"]: {"stdout_lines": result.stdout.splitlines()}},
        )
        return result, changed

    def _assertions(self, settings: list[str]) -> dict[str, bool]:
        readback_task = _task("ansible.builtin.command", 1)
        result = self._rails_r(readback_task, settings)
        self.assertEqual(result.returncode, 0, result.stderr)
        assert_task = _task("ansible.builtin.assert")
        loop_var = assert_task["loop_control"]["loop_var"]
        items = _render(
            assert_task["loop"], DISCOURSE_CHAT_INTEGRATION_SETTINGS=settings
        )
        readback = {"stdout_lines": result.stdout.splitlines()}
        return {
            item: all(
                _evaluate(
                    condition,
                    **{loop_var: item, readback_task["register"]: readback},
                )
                for condition in assert_task["ansible.builtin.assert"]["that"]
            )
            for item in items
        }

    def test_a_matrix_round_switches_on_the_plugin_and_the_matrix_provider(
        self,
    ) -> None:
        self.assertEqual(_settings(matrix=True, mattermost=False), [PLUGIN, MATRIX])

    def test_a_mattermost_round_switches_on_the_mattermost_provider(self) -> None:
        self.assertEqual(_settings(matrix=False, mattermost=True), [PLUGIN, MATTERMOST])

    def test_a_round_with_both_partners_switches_on_both_providers(self) -> None:
        self.assertEqual(
            _settings(matrix=True, mattermost=True), [PLUGIN, MATRIX, MATTERMOST]
        )

    def test_a_fresh_instance_is_changed_and_reads_back_enabled(self) -> None:
        self._seed({PLUGIN: False, MATRIX: False, MATTERMOST: False})
        settings = _settings(matrix=True, mattermost=False)

        result, changed = self._write(settings)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(changed, result.stdout)
        self.assertEqual(self._assertions(settings), {PLUGIN: True, MATRIX: True})

    def test_an_undeployed_partner_keeps_its_provider_setting(self) -> None:
        self._seed({PLUGIN: False, MATRIX: False, MATTERMOST: False})

        result, _ = self._write(_settings(matrix=True, mattermost=False))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self._stored()[MATTERMOST])

    def test_a_converged_instance_reports_no_change(self) -> None:
        seeded = {PLUGIN: True, MATRIX: True, MATTERMOST: False}
        self._seed(seeded)

        result, changed = self._write(_settings(matrix=True, mattermost=False))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(changed, result.stdout)
        self.assertEqual(self._stored(), seeded)

    def test_a_setting_that_does_not_stick_fails_the_assert(self) -> None:
        self._seed({PLUGIN: False, MATRIX: False, MATTERMOST: False})
        settings = _settings(matrix=True, mattermost=False)

        result, _ = self._write(settings, drop_writes=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._assertions(settings), {PLUGIN: False, MATRIX: False})

    def test_an_image_without_the_plugin_fails_the_write(self) -> None:
        self._seed({MATRIX: False, MATTERMOST: False})

        result, _ = self._write(_settings(matrix=True, mattermost=False))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NoMethodError", result.stderr)


class TestChatIntegrationWiring(unittest.TestCase):
    def test_the_stack_host_play_includes_the_addon_behind_its_gate(self) -> None:
        includes = [
            task
            for task in load_yaml_any(str(STACK_HOST))
            if task.get("include_tasks") == "addons/discourse-chat-integration.yml"
        ]

        self.assertEqual(len(includes), 1, includes)
        self.assertEqual(
            includes[0]["when"], "DISCOURSE_CHAT_INTEGRATION_ENABLED | bool"
        )

    def test_the_gate_follows_the_addon_enable_state(self) -> None:
        gate = load_yaml_any(str(VARS))["DISCOURSE_CHAT_INTEGRATION_ENABLED"]
        environment = NativeEnvironment(undefined=StrictUndefined)
        environment.filters["bool"] = lambda value: str(value).lower() == "true"

        for enabled in ("True", "False"):
            with self.subTest(enabled=enabled):
                lookup = _config_lookup(
                    {"addons.discourse-chat-integration.enabled": enabled}
                )
                self.assertIs(
                    environment.from_string(gate).render(
                        lookup=lookup, application_id=APPLICATION_ID
                    ),
                    enabled == "True",
                )


if __name__ == "__main__":
    unittest.main()
