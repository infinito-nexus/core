from __future__ import annotations

import unittest

from tests.utils.django_stubs import load

from . import APP, AUTH_USER_MODEL


class TestSsoSubjectModel(unittest.TestCase):
    def setUp(self):
        self.model = load(APP, "models.py").SsoSubject

    def test_each_account_holds_at_most_one_subject_and_loses_it_with_the_account(
        self,
    ):
        self.assertEqual(self.model.user.kind, "OneToOneField")
        self.assertEqual(self.model.user.args, (AUTH_USER_MODEL,))
        self.assertEqual(
            self.model.user.kwargs,
            {"on_delete": "CASCADE", "related_name": "infinito_sso_subject"},
        )

    def test_a_keycloak_username_binds_exactly_one_account(self):
        self.assertEqual(self.model.username.kind, "CharField")
        self.assertEqual(
            self.model.username.kwargs,
            {"max_length": 255, "unique": True},
            "infinito_sso.py resolves the account by this username alone, so two "
            "rows with one username would hand a login either account",
        )


if __name__ == "__main__":
    unittest.main()
