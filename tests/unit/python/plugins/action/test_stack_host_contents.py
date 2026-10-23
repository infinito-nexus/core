import unittest
from unittest.mock import MagicMock, patch

from plugins.action.stack_host_contents import ActionModule


class _FakeTask:
    def __init__(self, *, args=None):
        self.args = {} if args is None else dict(args)


class _FakeTemplar:
    def __init__(self, *, is_stack_host=True):
        self._is_stack_host = is_stack_host
        self.available_variables: dict[str, object] = {}

    def template(self, raw):
        return self._is_stack_host


_ARGS = {"files": [{"path": "/etc/x.conf", "content": "x"}], "mode": "0644"}


def _make_action(task, templar):
    action = object.__new__(ActionModule)
    action._task = task
    action._templar = templar
    action._execute_module = MagicMock(
        return_value={"changed": True, "changed_paths": ["/etc/x.conf"]}
    )
    return action


class TestStackHostContents(unittest.TestCase):
    def test_skips_silently_on_non_stack_host(self):
        action = _make_action(_FakeTask(args=_ARGS), _FakeTemplar(is_stack_host=False))

        result = action.run(task_vars={})

        self.assertTrue(result["skipped"])
        self.assertFalse(result["changed"])
        self.assertIn("IS_STACK_HOST", result["skip_reason"])
        action._execute_module.assert_not_called()

    def test_writes_every_file_in_one_module_call_on_stack_host(self):
        action = _make_action(_FakeTask(args=_ARGS), _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_contents.ActionBase.run", return_value={}
        ):
            result = action.run(task_vars={"IS_STACK_HOST": True})

        action._execute_module.assert_called_once_with(
            module_name="stack_host_contents",
            module_args=_ARGS,
            task_vars={"IS_STACK_HOST": True},
        )
        self.assertEqual(result["changed_paths"], ["/etc/x.conf"])


if __name__ == "__main__":
    unittest.main()
