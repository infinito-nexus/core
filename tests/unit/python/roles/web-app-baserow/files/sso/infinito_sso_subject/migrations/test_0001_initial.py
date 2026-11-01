from __future__ import annotations

import unittest

from tests.utils.django_stubs import AUTH_USER_MODEL, load

from . import PROJECT_ROOT

APP = PROJECT_ROOT / "roles/web-app-baserow/files/sso/infinito_sso_subject"


class TestInitialMigration(unittest.TestCase):
    def setUp(self):
        self.migration = load(APP, "migrations/0001_initial.py").Migration
        self.model = load(APP, "models.py").SsoSubject

    def test_depends_on_the_user_model(self):
        self.assertTrue(self.migration.initial)
        self.assertEqual(
            self.migration.dependencies, [("__setting__", AUTH_USER_MODEL)]
        )

    def test_creates_the_table_the_model_declares(self):
        [operation] = self.migration.operations
        self.assertEqual(
            (operation.operation, operation.name), ("CreateModel", "SsoSubject")
        )
        fields = dict(operation.fields)
        self.assertEqual(set(fields), {"id", "username", "user"})
        self.assertEqual(fields["id"].kind, "AutoField")
        self.assertTrue(fields["id"].kwargs["primary_key"])
        self.assertEqual(
            (fields["username"].kind, fields["username"].kwargs),
            (self.model.username.kind, self.model.username.kwargs),
        )
        self.assertEqual(fields["user"].kind, self.model.user.kind)
        self.assertEqual(
            fields["user"].kwargs,
            {**self.model.user.kwargs, "to": AUTH_USER_MODEL},
        )


if __name__ == "__main__":
    unittest.main()
