import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleActionFail

from plugins.action.database_query import ActionModule


class _FakeTask:
    def __init__(self, *, args=None):
        self.args = {} if args is None else dict(args)


class _FakeTemplar:
    def __init__(self):
        self.available_variables: dict[str, object] = {}

    def template(self, raw):
        return raw


def _make_action(task):
    action = object.__new__(ActionModule)
    action._task = task
    action._templar = _FakeTemplar()
    action._execute_module = MagicMock(return_value={"changed": True, "rows": []})
    return action


class TestDatabaseQueryAction(unittest.TestCase):
    def setUp(self):
        patcher = patch("plugins.action.database_query.ActionBase.run", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sent_args(self, action):
        return action._execute_module.call_args.kwargs["module_args"]

    def test_reads_query_file_on_controller_and_passes_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql = Path(tmp) / "q.sql"
            sql.write_text("SELECT 1;\n", encoding="utf-8")
            task = _FakeTask(args={"config": {"x": 1}, "query_file": str(sql)})
            action = _make_action(task)

            action.run(task_vars={})

            sent = self._sent_args(action)
            self.assertEqual(sent["query"], "SELECT 1;\n")
            self.assertNotIn("query_file", sent)
            self.assertEqual(sent["config"], {"x": 1})

    def test_passes_inline_query_unchanged(self):
        task = _FakeTask(args={"config": {}, "query": "SELECT 2;"})
        action = _make_action(task)

        action.run(task_vars={})

        sent = self._sent_args(action)
        self.assertEqual(sent["query"], "SELECT 2;")
        self.assertNotIn("query_file", sent)

    def test_inline_query_takes_precedence_when_both_present(self):
        task = _FakeTask(args={"query": "SELECT 3;", "query_file": "/nope.sql"})
        action = _make_action(task)

        action.run(task_vars={})

        sent = self._sent_args(action)
        self.assertEqual(sent["query"], "SELECT 3;")
        self.assertEqual(sent["query_file"], "/nope.sql")

    def test_missing_query_file_raises(self):
        task = _FakeTask(args={"query_file": "/does/not/exist.sql"})
        action = _make_action(task)

        with self.assertRaises(AnsibleActionFail):
            action.run(task_vars={})

    def test_seeds_templar_with_task_vars(self):
        task = _FakeTask(args={"query": "SELECT 1;"})
        action = _make_action(task)

        action.run(task_vars={"role_path": "/x"})

        self.assertEqual(action._templar.available_variables.get("role_path"), "/x")


if __name__ == "__main__":
    unittest.main()
