import unittest
from unittest.mock import patch

from plugins.action.stack_host_template import ActionModule


class _FakeTask:
    def __init__(self, *, args=None):
        self.args = {} if args is None else dict(args)


class _FakeTemplar:
    def __init__(self, *, is_stack_host=True):
        self._is_stack_host = is_stack_host
        self.available_variables: dict[str, object] = {}

    def template(self, raw):
        return self._is_stack_host


def _make_action(task, templar):
    action = object.__new__(ActionModule)
    action._task = task
    action._templar = templar
    return action


class TestStackHostTemplate(unittest.TestCase):
    def test_skips_silently_on_non_stack_host(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf"})
        action = _make_action(task, _FakeTemplar(is_stack_host=False))

        result = action.run(task_vars={})

        self.assertTrue(result["skipped"])
        self.assertFalse(result["changed"])
        self.assertIn("IS_STACK_HOST", result["skip_reason"])

    def test_skips_when_templar_returns_string_false(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf"})
        action = _make_action(task, _FakeTemplar(is_stack_host="False"))

        result = action.run(task_vars={})

        self.assertTrue(result["skipped"])

    def test_delegates_to_template_on_stack_host(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_template.TemplateActionModule.run",
            return_value={"changed": True},
        ) as super_run:
            action.run(task_vars={})

        super_run.assert_called_once()

    def test_seeds_templar_with_task_vars_before_rendering(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf"})
        templar = _FakeTemplar(is_stack_host=True)
        action = _make_action(task, templar)

        with patch(
            "plugins.action.stack_host_template.TemplateActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={"IS_STACK_HOST": True, "ANSIBLE_VERSION": "9.0"})

        self.assertEqual(templar.available_variables.get("IS_STACK_HOST"), True)
        self.assertEqual(templar.available_variables.get("ANSIBLE_VERSION"), "9.0")

    def test_defaults_mode_to_0644_when_unset(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_template.TemplateActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={})

        self.assertEqual(task.args["mode"], "0644")

    def test_keeps_caller_supplied_mode(self):
        task = _FakeTask(args={"src": "x.j2", "dest": "/etc/x.conf", "mode": "0600"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_template.TemplateActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={})

        self.assertEqual(task.args["mode"], "0600")

    def test_is_stack_host_expr_carries_trust_tag(self):
        from ansible.template import is_trusted_as_template

        from plugins.action.stack_host_template import _IS_STACK_HOST_EXPR

        self.assertTrue(
            is_trusted_as_template(_IS_STACK_HOST_EXPR),
            "The IS_STACK_HOST template expression must carry the TrustedAsTemplate "
            "tag; otherwise Ansible 2.19+ returns the literal string unchanged.",
        )


if __name__ == "__main__":
    unittest.main()
