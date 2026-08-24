import unittest
from unittest.mock import patch

from plugins.action.uri_retry import ActionModule


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


class TestUriRetryActionPlugin(unittest.TestCase):
    def test_run_uses_default_retry_policy(self):
        task = _FakeTask(args={"url": "http://example.invalid"})
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                side_effect=[
                    {"failed": True, "msg": "temporary"},
                    {"failed": False, "status": 200},
                ],
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("status"), 200)
        self.assertEqual(result.get("attempts"), 2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2)

    def test_run_honors_standard_retries_and_delay_keywords(self):
        task = _FakeTask(
            args={"url": "http://example.invalid"},
            ds={"retries": 2, "delay": 1},
            retries=2,
            delay=1,
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                side_effect=[
                    {"failed": True, "msg": "attempt-1"},
                    {"failed": True, "msg": "attempt-2"},
                    {"failed": False, "status": 200},
                ],
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("status"), 200)
        self.assertEqual(result.get("attempts"), 3)
        self.assertEqual(run_mock.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_called_with(1)

    def test_run_delegates_to_native_when_until_is_set(self):
        task = _FakeTask(
            args={"url": "http://example.invalid"},
            ds={"until": "uri_result.status == 200"},
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                return_value={"failed": True, "msg": "native-until"},
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(run_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_run_does_not_retry_for_async_tasks(self):
        task = _FakeTask(
            args={"url": "http://example.invalid"},
            async_val=30,
        )
        action = _make_action(task)

        with patch(
            "plugins.action.uri_retry.UriActionModule.run",
            autospec=True,
            return_value={"failed": True, "msg": "async path"},
        ) as run_mock:
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(run_mock.call_count, 1)

    def test_failed_result_contains_attempts_after_exhausting_retries(self):
        task = _FakeTask(
            args={"url": "http://example.invalid"},
            ds={"retries": 1, "delay": 1},
            retries=1,
            delay=1,
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                side_effect=[
                    {"failed": True, "msg": "attempt-1"},
                    {"failed": True, "msg": "attempt-2"},
                ],
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertTrue(result.get("failed"))
        self.assertEqual(result.get("attempts"), 2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)

    def test_attempts_is_overwritten_with_real_retry_count(self):
        task = _FakeTask(
            args={"url": "http://example.invalid"},
            ds={"retries": 2, "delay": 1},
            retries=2,
            delay=1,
        )
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                side_effect=[
                    {"failed": True, "msg": "attempt-1", "attempts": 1},
                    {"failed": False, "status": 200, "attempts": 1},
                ],
            ),
            patch("plugins.action.uri_retry.time.sleep"),
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("attempts"), 2)


if __name__ == "__main__":
    unittest.main()
