import unittest
from unittest.mock import patch

from plugins.action.uri_probe import ActionModule


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


class TestUriProbeActionPlugin(unittest.TestCase):
    def test_run_uses_probe_defaults_and_short_retry_budget(self):
        task = _FakeTask(args={"url": "http://example.invalid"})
        action = _make_action(task)

        with (
            patch(
                "plugins.action.uri_retry.UriActionModule.run",
                autospec=True,
                side_effect=[
                    {"failed": True, "msg": "temporary"},
                    {"failed": True, "msg": "temporary-again"},
                    {"failed": True, "msg": "still-down"},
                ],
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(task.args["method"], "HEAD")
        self.assertEqual(task.args["timeout"], 5)
        self.assertTrue(result.get("failed"))
        self.assertEqual(result.get("attempts"), 3)
        self.assertEqual(run_mock.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_called_with(2)

    def test_run_preserves_explicit_method_and_timeout(self):
        task = _FakeTask(
            args={
                "url": "http://example.invalid",
                "method": "GET",
                "timeout": 9,
            }
        )
        action = _make_action(task)

        with patch(
            "plugins.action.uri_probe.UriRetryActionModule.run",
            autospec=True,
            return_value={"failed": False, "status": 204},
        ) as run_mock:
            result = action.run(task_vars={})

        self.assertEqual(task.args["method"], "GET")
        self.assertEqual(task.args["timeout"], 9)
        self.assertEqual(result.get("status"), 204)
        self.assertEqual(run_mock.call_count, 1)

    def test_run_honors_explicit_retry_keywords(self):
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
                    {"failed": False, "status": 200},
                ],
            ) as run_mock,
            patch("plugins.action.uri_retry.time.sleep") as sleep_mock,
        ):
            result = action.run(task_vars={})

        self.assertEqual(result.get("status"), 200)
        self.assertEqual(result.get("attempts"), 2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
