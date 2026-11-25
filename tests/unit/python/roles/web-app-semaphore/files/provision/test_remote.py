from __future__ import annotations

import unittest
import unittest.mock as mock

from ._fake_provision import (
    JWT,
    STATE_KEYS,
    TOKEN,
    WORKSPACE,
    FakePlatform,
    load,
)

remote = load("provision.remote")

SECRET = f"tenant/data/{WORKSPACE}-provision/s3"


class TestRequest(unittest.TestCase):
    def test_plain_http_is_refused_off_loopback(self):
        for url in (
            "http://192.0.2.1/v1/x",
            "http://bao.example.org/v1/x",
            "ftp://[::1]/x",
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(remote.RemoteError, "no https origin"),
            ):
                remote.request(url, "GET", {}, None, "")


class PlatformCase(unittest.TestCase):
    def setUp(self):
        self.platform = FakePlatform({SECRET: dict(STATE_KEYS)}, {"b/k": b"state"})
        self.addCleanup(self.platform.stop)


class TestOpenBao(PlatformCase):
    def test_login_keeps_the_token_for_reads(self):
        bao = remote.OpenBao(self.platform.origin + "/", "")
        self.assertEqual(bao.login(f"{WORKSPACE}-provision", JWT), TOKEN)
        self.assertEqual(
            bao.read(SECRET, ["access_key"]), {"access_key": "STATEACCESSKEY0001"}
        )
        self.assertEqual(self.platform.reads, [SECRET])

    def test_a_refused_login_or_read_raises_without_the_token(self):
        bao = remote.OpenBao(self.platform.origin, "")
        with self.assertRaisesRegex(remote.RemoteError, "auth/jwt/login: HTTP 400"):
            bao.login("ws-other-provision", JWT)
        with self.assertRaisesRegex(remote.RemoteError, "HTTP 403"):
            bao.read(SECRET, ["access_key"])

    def test_a_missing_field_is_named(self):
        bao = remote.OpenBao(self.platform.origin, "")
        bao.login(f"{WORKSPACE}-provision", JWT)
        with self.assertRaisesRegex(remote.RemoteError, "lacks region$"):
            bao.read(SECRET, ["access_key", "region"])


class TestStateBucket(PlatformCase):
    def bucket(self, access_key):
        return remote.StateBucket(
            self.platform.origin, access_key, STATE_KEYS["secret_key"], "us-east-1", ""
        )

    def test_objects_are_read_with_the_workspace_identity(self):
        bucket = self.bucket(STATE_KEYS["access_key"])
        self.assertEqual(bucket.get("b", "k"), b"state")
        self.assertIsNone(bucket.get("b", "k.tflock"))
        self.assertTrue(bucket.exists("b", "k"))
        self.assertFalse(bucket.exists("b", "missing"))
        self.assertEqual(
            self.platform.s3_requests,
            [
                ("GET", "/b/k"),
                ("GET", "/b/k.tflock"),
                ("HEAD", "/b/k"),
                ("HEAD", "/b/missing"),
            ],
        )

    def test_a_foreign_identity_fails(self):
        with self.assertRaisesRegex(remote.RemoteError, "S3 HEAD b/k: HTTP 403"):
            self.bucket("OTHERACCESSKEY").exists("b", "k")

    def test_negative_control_a_wrong_secret_key_fails_the_signature(self):
        bucket = remote.StateBucket(
            self.platform.origin,
            STATE_KEYS["access_key"],
            "not-the-secret",
            "us-east-1",
            "",
        )
        with self.assertRaisesRegex(remote.RemoteError, "S3 HEAD b/k: HTTP 403"):
            bucket.exists("b", "k")

    def test_put_signs_the_sha256_of_its_body(self):
        body = b'{"provider": "incus"}'
        self.bucket(STATE_KEYS["access_key"]).put("b", "SO-1/1.provision.json", body)
        self.assertEqual(self.platform.objects["b/SO-1/1.provision.json"], body)
        self.assertEqual(
            self.platform.s3_requests, [("PUT", "/b/SO-1/1.provision.json")]
        )

    def test_negative_control_a_body_other_than_the_signed_one_is_refused(self):
        sent = remote.request

        def swapped(url, method, headers, body, cafile):
            return sent(url, method, headers, b'{"provider": "hetzner"}', cafile)

        with (
            mock.patch.object(remote, "request", swapped),
            self.assertRaisesRegex(remote.RemoteError, "S3 PUT b/k2: HTTP 403"),
        ):
            self.bucket(STATE_KEYS["access_key"]).put("b", "k2", b'{"provider": "x"}')
        self.assertNotIn("b/k2", self.platform.objects)


if __name__ == "__main__":
    unittest.main()
