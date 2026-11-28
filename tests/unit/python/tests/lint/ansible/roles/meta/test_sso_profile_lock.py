"""Negative controls for the SSO profile lock lint, custom roles included."""

from __future__ import annotations

import unittest
from typing import Any

from tests.lint.ansible.roles.meta import test_sso_profile_lock as lint

SSO = "{{ 'web-app-keycloak' in group_names }}"
CUSTOM = "web-app-cst-fixture"
IN_TREE = "web-app-fixture"
LISTED = "web-app-grafana"
PENDING_ROLE = "web-app-baserow"
MARKER = r"body\.cst-sso\s+\S.*"

LOCKING: dict[str, Any] = {
    "overwritten": ["name", "avatar"],
    "languages": ["en"],
    "marker": MARKER,
}
LOCKED: dict[str, str] = {
    "name": "body.cst-sso #name",
    "avatar": "body.cst-sso #avatar",
}


BARE: dict[str, Any] = {"sso": {"enabled": SSO}}
WITHOUT_IDENTITY: dict[str, Any] = {"sso": {"enabled": "false"}}


def services(profile: dict[str, Any]) -> dict[str, Any]:
    """A parsed ``meta/services.yml`` whose enabled ``sso`` block carries *profile*.

    Args:
        profile: ``services.sso.profile``.
    """
    return {"sso": {"enabled": SSO, "profile": profile}}


def forms(locked: dict[str, str]) -> dict[str, Any]:
    """A parsed ``meta/forms.yml`` with one ``sso.<ATTRIBUTE>`` field per entry.

    Args:
        locked: field mapped to its selector.
    """
    return {
        "profile": {
            "path": "/",
            "fields": {
                field: {"source": "sso.NAME", "mode": "enforced", "selector": selector}
                for field, selector in locked.items()
            },
        }
    }


def without(profile: dict[str, Any], *keys: str) -> dict[str, Any]:
    """*profile* without *keys*.

    Args:
        profile: a ``services.sso.profile`` mapping.
        keys: the keys to drop.
    """
    return {key: value for key, value in profile.items() if key not in keys}


class TestClassification(unittest.TestCase):
    def test_a_custom_role_with_sso_and_no_classification_fails(self) -> None:
        self.assertEqual([CUSTOM], lint.unclassified_roles({CUSTOM: BARE}))

    def test_an_in_tree_role_with_sso_and_no_classification_fails(self) -> None:
        self.assertEqual([IN_TREE], lint.unclassified_roles({IN_TREE: BARE}))

    def test_a_role_without_sso_or_ldap_needs_no_classification(self) -> None:
        self.assertEqual([], lint.unclassified_roles({CUSTOM: WITHOUT_IDENTITY}))

    def test_a_custom_role_needing_no_treatment_classifies_itself(self) -> None:
        roles = {CUSTOM: services({"none_needed": "identity per request"})}

        self.assertEqual([], lint.unclassified_roles(roles))
        self.assertEqual([], lint.schema_errors(roles))
        self.assertNotIn(CUSTOM, lint.uncovered_fields(roles))

    def test_a_custom_role_listing_its_overwritten_fields_passes(self) -> None:
        roles = {CUSTOM: services(LOCKING)}
        locks = {CUSTOM: forms(LOCKED)}

        self.assertEqual([], lint.unclassified_roles(roles))
        self.assertEqual([], lint.schema_errors(roles, locks))
        self.assertNotIn(CUSTOM, lint.uncovered_fields(roles, locks))
        self.assertEqual([], lint.marker_errors(roles, locks))

    def test_a_listed_role_is_classified_once(self) -> None:
        roles = {LISTED: BARE, PENDING_ROLE: BARE}

        self.assertEqual([], lint.unclassified_roles(roles))
        self.assertEqual([], lint.doubly_classified_roles(roles))

    def test_a_listed_role_classifying_itself_too_is_classified_twice(self) -> None:
        roles = {PENDING_ROLE: services({"none_needed": "gate only"})}

        self.assertEqual([PENDING_ROLE], lint.doubly_classified_roles(roles))


class TestCoverage(unittest.TestCase):
    def test_an_own_overwritten_field_left_unlocked_fails(self) -> None:
        locks = {CUSTOM: forms({"name": LOCKED["name"]})}

        self.assertEqual(
            ["avatar"],
            lint.uncovered_fields({CUSTOM: services(LOCKING)}, locks)[CUSTOM],
        )

    def test_a_field_of_the_forms_file_covers_an_overwritten_field(self) -> None:
        roles = {CUSTOM: services(LOCKING)}

        self.assertEqual(["avatar", "name"], lint.uncovered_fields(roles)[CUSTOM])
        self.assertNotIn(CUSTOM, lint.uncovered_fields(roles, {CUSTOM: forms(LOCKED)}))

    def test_the_inventory_fields_of_a_listed_role_still_count(self) -> None:
        self.assertEqual(
            ["email", "name", "username"],
            lint.uncovered_fields({LISTED: BARE})[LISTED],
        )

    def test_a_listed_role_missing_from_the_tree_counts_as_unlocked(self) -> None:
        self.assertEqual(
            ["email", "name", "username"], lint.uncovered_fields({})[LISTED]
        )


class TestSchema(unittest.TestCase):
    def errors(
        self, role: str, profile: dict[str, Any], locked: dict[str, str] | None = None
    ) -> str:
        locks = {role: forms(locked)} if locked else {}
        return "\n".join(lint.schema_errors({role: services(profile)}, locks))

    def test_the_old_locked_key_points_to_the_forms_file(self) -> None:
        profile = {**LOCKING, "locked": LOCKED}

        self.assertIn(
            "services.sso.profile.locked moved to meta/forms.yml",
            self.errors(CUSTOM, profile, LOCKED),
        )

    def test_none_needed_excludes_every_other_key(self) -> None:
        profile = {"none_needed": "gate only", "languages": ["en"]}

        self.assertIn("none_needed excludes `languages`", self.errors(CUSTOM, profile))

    def test_none_needed_without_a_reason_fails(self) -> None:
        self.assertIn(
            "none_needed must state why", self.errors(CUSTOM, {"none_needed": " "})
        )

    def test_an_empty_overwritten_list_fails(self) -> None:
        self.assertIn(
            "overwritten must list the fields", self.errors(CUSTOM, {"overwritten": []})
        )

    def test_a_locked_field_the_role_does_not_list_as_overwritten_fails(self) -> None:
        profile = {**LOCKING, "overwritten": ["name"]}

        self.assertIn(
            "locks avatar, which is not a known field",
            self.errors(CUSTOM, profile, LOCKED),
        )

    def test_a_locking_role_without_languages_fails(self) -> None:
        self.assertIn(
            "languages must list the UI languages",
            self.errors(CUSTOM, without(LOCKING, "languages"), LOCKED),
        )

    def test_a_locking_role_without_a_profile_block_fails(self) -> None:
        errors = lint.schema_errors({CUSTOM: BARE}, {CUSTOM: forms(LOCKED)})

        self.assertIn("services.sso.profile must be a non-empty mapping", errors[0])

    def test_a_marker_duplicating_managed_marker_fails(self) -> None:
        profile = {"languages": ["en"], "marker": MARKER}

        self.assertIn(
            "duplicates MANAGED_MARKER",
            self.errors(LISTED, profile, {"name": "#edit-user-profile-name:disabled"}),
        )

    def test_a_marker_that_is_no_regular_expression_fails(self) -> None:
        profile = {**LOCKING, "marker": "body(.cst-sso"}

        self.assertIn(
            "marker is no regular expression", self.errors(CUSTOM, profile, LOCKED)
        )

    def test_a_marker_without_locked_selectors_fails(self) -> None:
        profile = {"overwritten": ["name"], "write_back": ["name"], "marker": MARKER}

        self.assertIn(
            "marker needs the sso.<ATTRIBUTE> fields of meta/forms.yml",
            self.errors(CUSTOM, profile),
        )


class TestMarker(unittest.TestCase):
    def test_a_selector_part_without_the_meta_marker_fails(self) -> None:
        locked = {**LOCKED, "name": "body.cst-sso #name, #name"}
        roles = {CUSTOM: services(LOCKING)}

        self.assertEqual(
            [f"{CUSTOM}: name: #name"],
            lint.marker_errors(roles, {CUSTOM: forms(locked)}),
        )

    def test_a_locking_role_without_any_marker_fails(self) -> None:
        roles = {CUSTOM: services(without(LOCKING, "marker"))}

        errors = lint.marker_errors(roles, {CUSTOM: forms(LOCKED)})

        self.assertEqual(1, len(errors))
        self.assertIn("MANAGED_MARKER or as services.sso.profile.marker", errors[0])

    def test_a_role_without_forms_locks_nothing_to_mark(self) -> None:
        roles = {CUSTOM: services(without(LOCKING, "marker"))}

        self.assertEqual([], lint.marker_errors(roles))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
