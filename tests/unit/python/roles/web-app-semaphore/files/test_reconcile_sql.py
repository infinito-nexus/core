"""The RBAC reconcile of Semaphore keeps the shape its hook and the timer rely on."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SQL = ROLE / "files" / "sql" / "rbac" / "reconcile.sql"
RBAC_TASKS = ROLE / "tasks" / "03_rbac.yml"


def statements(text):
    return [part.strip() for part in re.split(r"\\set \w+ :ROW_COUNT", text)]


class ReconcileSqlTests(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(SQL))
        self.counters = re.findall(r"\\set (\w+) :ROW_COUNT", self.text)

    def test_every_variable_the_file_reads_is_passed_by_the_hook(self):
        tasks = read_text(str(RBAC_TASKS))
        for variable in re.findall(r"\\getenv \w+ (\w+)", self.text):
            with self.subTest(variable=variable):
                self.assertRegex(tasks, rf"\b{variable}\b")

    def test_the_unchanged_line_sums_every_counter(self):
        unchanged = self.text[self.text.index("SELECT 'UNCHANGED'") :]
        self.assertEqual(len(self.counters), len(set(self.counters)))
        for counter in self.counters:
            with self.subTest(counter=counter):
                self.assertIn(f":{counter}", unchanged)

    def test_every_write_reports_what_it_changed(self):
        for statement in statements(self.text)[:-1]:
            with self.subTest(statement=statement[:60]):
                self.assertRegex(statement, r"(RETURNING|SELECT) 'CHANGED ")

    def test_operators_are_pre_created_without_the_admin_flag(self):
        creation = next(
            s
            for s in statements(self.text)
            if "->'operator'" in s and 'INSERT INTO public."user"' in s
        )
        self.assertRegex(creation, r"'', FALSE, TRUE\s")

    def test_grants_touch_only_task_runner_rows_of_the_provisioned_project(self):
        grants = [
            s
            for s in statements(self.text)
            if "public.project__user" in s and ":'deploy_project'" not in s
        ]
        self.assertEqual(len(grants), 3)
        for statement in grants:
            with self.subTest(statement=statement[-80:]):
                self.assertIn("WHERE name = :'project'", statement)
                self.assertIn("task_runner", statement)
        promote, revoke = grants[1], grants[2]
        self.assertIn("AND granted.role = 'guest'", promote)
        self.assertIn("AND granted.role = 'task_runner'", revoke)

    def test_only_administrators_are_members_of_the_deploy_project(self):
        deploy = [s for s in statements(self.text) if ":'deploy_project'" in s]
        self.assertEqual(len(deploy), 2)
        grant, revoke = deploy
        for statement in deploy:
            with self.subTest(statement=statement[-80:]):
                self.assertIn("WHERE name = :'deploy_project'", statement)
                self.assertNotIn("task_runner", statement)
                self.assertNotIn("->'operator'", statement)
        self.assertIn("WHERE account.admin", grant)
        self.assertIn("'owner'", grant)
        self.assertIn("DELETE FROM public.project__user", revoke)
        self.assertIn("AND NOT account.admin", revoke)


if __name__ == "__main__":
    unittest.main()
