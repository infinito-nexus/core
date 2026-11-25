from __future__ import annotations

import unittest

from provider import store


class Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value


class TestAccounts(unittest.TestCase):
    def setUp(self) -> None:
        self.store = store.Store()

    def test_an_account_signs_in_with_its_password_only(self) -> None:
        account = self.store.create_account("Ada Lovelace", "Ada@Example.org", "s3cret")
        self.assertEqual(self.store.authenticate("ada@example.org", "s3cret"), account)
        self.assertIsNone(self.store.authenticate("ada@example.org", "wrong"))
        self.assertIsNone(self.store.authenticate("nobody@example.org", "s3cret"))

    def test_the_password_is_never_stored_in_plaintext(self) -> None:
        account = self.store.create_account("Ada", "ada@example.org", "s3cret")
        self.assertNotIn("s3cret", account.password_hash)

    def test_an_email_belongs_to_one_account(self) -> None:
        self.store.create_account("Ada", "ada@example.org", "s3cret")
        with self.assertRaises(store.StoreError):
            self.store.create_account("Ada Again", "ADA@example.org", "other")

    def test_empty_fields_are_refused(self) -> None:
        with self.assertRaises(store.StoreError):
            self.store.create_account(" ", "ada@example.org", "s3cret")


class TestGrants(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.store = store.Store(now=self.clock)
        self.member = self.store.create_account("Ada", "ada@example.org", "pw").member

    def test_a_code_is_redeemed_once_by_its_client(self) -> None:
        code = self.store.issue_code(self.member, "client", "https://app/cb", "openid")
        grant = self.store.redeem_code(code, "client", "https://app/cb")
        self.assertEqual(grant.member, self.member)
        with self.assertRaises(store.StoreError):
            self.store.redeem_code(code, "client", "https://app/cb")

    def test_a_code_for_another_client_or_redirect_is_refused(self) -> None:
        code = self.store.issue_code(self.member, "client", "https://app/cb", "openid")
        with self.assertRaises(store.StoreError):
            self.store.redeem_code(code, "client", "https://evil/cb")

    def test_an_expired_code_is_refused(self) -> None:
        code = self.store.issue_code(self.member, "client", "https://app/cb", "openid")
        self.clock.value += store.CODE_SECONDS + 1
        with self.assertRaises(store.StoreError):
            self.store.redeem_code(code, "client", "https://app/cb")

    def test_tokens_identify_the_member_until_they_expire(self) -> None:
        tokens = self.store.issue_tokens(self.member, "openid")
        self.assertEqual(
            self.store.member_for(tokens["access_token"]).member, self.member
        )
        self.clock.value += store.ACCESS_SECONDS + 1
        self.assertIsNone(self.store.member_for(tokens["access_token"]))

    def test_a_refresh_keeps_the_refresh_token_and_issues_a_new_access_token(
        self,
    ) -> None:
        tokens = self.store.issue_tokens(self.member, "openid")
        refreshed = self.store.refresh(tokens["refresh_token"])
        self.assertEqual(refreshed["refresh_token"], tokens["refresh_token"])
        self.assertNotEqual(refreshed["access_token"], tokens["access_token"])
        self.assertEqual(
            self.store.member_for(refreshed["access_token"]).member, self.member
        )

    def test_an_unknown_refresh_token_is_refused(self) -> None:
        with self.assertRaises(store.StoreError):
            self.store.refresh("nope")


class TestContent(unittest.TestCase):
    def setUp(self) -> None:
        self.store = store.Store()
        self.owner = self.store.create_account("Ada", "ada@example.org", "pw").urn

    def test_an_image_counts_as_uploaded_only_after_its_bytes_arrive(self) -> None:
        image = self.store.register_image(self.owner)
        self.assertFalse(self.store.uploaded(image.urn, self.owner))
        self.store.store_upload(image.upload_id, self.owner, b"\xff\xd8")
        self.assertTrue(self.store.uploaded(image.urn, self.owner))
        self.assertFalse(self.store.uploaded(image.urn, "urn:li:person:other"))

    def test_another_member_cannot_upload_into_an_image(self) -> None:
        image = self.store.register_image(self.owner)
        with self.assertRaises(store.StoreError):
            self.store.store_upload(image.upload_id, "urn:li:person:other", b"x")

    def test_posts_get_distinct_share_urns_and_can_be_read_back(self) -> None:
        first = self.store.create_post(self.owner, "one", "PUBLIC", {})
        second = self.store.create_post(self.owner, "two", "PUBLIC", {})
        self.assertNotEqual(first.id, second.id)
        self.assertRegex(first.id, r"^urn:li:share:[0-9]+$")
        self.assertEqual(self.store.post(second.id).commentary, "two")
        self.assertEqual(len(self.store.posts()), 2)


if __name__ == "__main__":
    unittest.main()
