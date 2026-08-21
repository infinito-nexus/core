import unittest
from unittest.mock import patch

from plugins.action.get_url_retry import ActionModule


class _FakeTask:
    def __init__(
        self,
        *,
        args=None,
        ds=None,
        async_val=0,
        retries=None,
        delay=0,
    ):
        self.args = {} if args is None else dict(args)
        self._ds = {} if ds is None else dict(ds)
        self.async_val = async_val
        self.retries = retries
        self.delay = delay

    def get_ds(self):
        return self._ds


def _make_action(task: _FakeTask) -> ActionModule:
    action = object.__new__(ActionModule)
    action._task = task
    return action


class TestGetUrlRetryActionPlugin(unittest.TestCase):
    def test_run_uses_default_retry_policy(self):
        task = _FakeTask(args={"url": "http://example.invalid", "dest": "/tmp/file"})
        action = _make_action(task)

        with (
            patch(
                "plugins.action.get_url_retry.ActionModule._execute_get_url",
                side_effect=[
                    {"failed": True, "msg": "temporary"},
                    {"failed": False, "dest": "/tmp/file"},
                ],
            ) as run_mock,
            patch("plugins.action.get_url_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("dest"), "/tmp/file")
        self.assertEqual(result.get("attempts"), 2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(5)

    def test_run_honors_standard_retries_and_delay_keywords(self):
        task = _FakeTask(
            args={"url": "http://example.invalid", "dest": "/tmp/file"},
            ds={"retries": 2, "delay": 1},
            retries=2,
            delay=1,
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.get_url_retry.ActionModule._execute_get_url",
                side_effect=[
                    {"failed": True, "msg": "attempt-1"},
                    {"failed": True, "msg": "attempt-2"},
                    {"failed": False, "dest": "/tmp/file"},
                ],
            ) as run_mock,
            patch("plugins.action.get_url_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("dest"), "/tmp/file")
        self.assertEqual(result.get("attempts"), 3)
        self.assertEqual(run_mock.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_called_with(1)

    def test_run_delegates_to_native_when_until_is_set(self):
        task = _FakeTask(
            args={"url": "http://example.invalid", "dest": "/tmp/file"},
            ds={"until": "download_result is succeeded"},
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.get_url_retry.ActionModule._execute_get_url",
                return_value={"failed": True, "msg": "native-until"},
            ) as run_mock,
            patch("plugins.action.get_url_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(run_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_run_does_not_retry_for_async_tasks(self):
        task = _FakeTask(
            args={"url": "http://example.invalid", "dest": "/tmp/file"},
            async_val=30,
        )
        action = _make_action(task)

        with patch(
            "plugins.action.get_url_retry.ActionModule._execute_get_url",
            return_value={"failed": True, "msg": "async path"},
        ) as run_mock:
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(run_mock.call_count, 1)

    def test_failed_result_contains_attempts_after_exhausting_retries(self):
        task = _FakeTask(
            args={"url": "http://example.invalid", "dest": "/tmp/file"},
            ds={"retries": 1, "delay": 1},
            retries=1,
            delay=1,
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.get_url_retry.ActionModule._execute_get_url",
                side_effect=[
                    {"failed": True, "msg": "attempt-1"},
                    {"failed": True, "msg": "attempt-2"},
                ],
            ) as run_mock,
            patch("plugins.action.get_url_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(result.get("attempts"), 2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
