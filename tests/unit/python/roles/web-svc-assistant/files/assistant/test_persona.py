from __future__ import annotations

import unittest

from . import load

persona = load("persona")

ADMIN_GROUP = "/roles/web-svc-assistant/administrator"


class TestPersona(unittest.TestCase):
    def test_an_anonymous_request_gets_end_user_support(self) -> None:
        self.assertEqual(persona.persona({}, ADMIN_GROUP), persona.END_USER)

    def test_a_signed_in_user_outside_the_group_gets_end_user_support(self) -> None:
        headers = {
            "X-Forwarded-Preferred-Username": "biber",
            "X-Forwarded-Groups": "/roles/web-app-gitea/administrator",
        }
        self.assertEqual(persona.persona(headers, ADMIN_GROUP), persona.END_USER)

    def test_a_member_of_the_administrator_group_gets_the_consultant(self) -> None:
        headers = {
            "x-forwarded-preferred-username": "administrator",
            "x-forwarded-groups": "roles/web-app-gitea/user, roles/web-svc-assistant/administrator",
        }
        self.assertEqual(persona.persona(headers, ADMIN_GROUP), persona.CONSULTANT)

    def test_groups_without_a_username_count_for_nothing(self) -> None:
        headers = {"X-Forwarded-Groups": ADMIN_GROUP}
        self.assertEqual(persona.persona(headers, ADMIN_GROUP), persona.END_USER)

    def test_a_group_whose_name_only_starts_with_the_admin_path_is_no_match(
        self,
    ) -> None:
        headers = {
            "X-Forwarded-Preferred-Username": "biber",
            "X-Forwarded-Groups": ADMIN_GROUP + "-candidates",
        }
        self.assertEqual(persona.persona(headers, ADMIN_GROUP), persona.END_USER)

    def test_an_empty_admin_group_never_grants_the_consultant(self) -> None:
        headers = {"X-Forwarded-Preferred-Username": "biber", "X-Forwarded-Groups": "/"}
        self.assertEqual(persona.persona(headers, ""), persona.END_USER)


class TestSignedIn(unittest.TestCase):
    def test_the_gate_names_the_user(self) -> None:
        self.assertTrue(persona.signed_in({"X-Forwarded-Preferred-Username": "biber"}))

    def test_a_blank_username_is_anonymous(self) -> None:
        self.assertFalse(persona.signed_in({"X-Forwarded-Preferred-Username": " "}))


if __name__ == "__main__":
    unittest.main()
