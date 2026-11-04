"""Pin the engine probe's SigV4 signer against independently produced vectors.

The expected signatures were generated with botocore 1.43.106, which the CLI
runner does not ship; freezing them here keeps the hand-rolled signer honest
without adding that dependency to every role's test image. A drift here means
every signed request in the engine probe would come back 403
SignatureDoesNotMatch against a healthy store.
"""

from __future__ import annotations

import sys
import unittest
from typing import ClassVar

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-svc-seaweedfs/files/test"))

from datetime import UTC

import sigv4

ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
REGION = "us-east-1"


class TestSigV4(unittest.TestCase):
    STAMP: ClassVar[str] = "20130524T000000Z"
    VECTORS: ClassVar[list[dict]] = [
        {
            "method": "GET",
            "host": "seaweedfs:8333",
            "path": "/",
            "query": None,
            "payload": b"",
            "signature": "741e224559611fe6adfe50315e98fec09bdb9a52da21c86b77ee676d98e00dd1",
        },
        {
            "method": "GET",
            "host": "seaweedfs:8333",
            "path": "/matrix",
            "query": {"list-type": "2", "max-keys": "1"},
            "payload": b"",
            "signature": "eee845a1bf4fa9439b3e9a3fe61ab440e0560036caacb71cc871c079fd4ad7b5",
        },
        {
            "method": "PUT",
            "host": "seaweedfs:8333",
            "path": "/infinito-engine-check-abc",
            "query": None,
            "payload": b"",
            "signature": "53e844ed6b237bdf9329204161e0c80a0f699c4032b4862f5ce4cb52ec737464",
        },
        {
            "method": "PUT",
            "host": "127.0.0.1:8085",
            "path": "/bucket/probe-deadbeef",
            "query": None,
            "payload": b"\x00\x01payload~bytes",
            "signature": "3946d221e2b6f49f2e9ea7929dde3ef2226aebc5344152bd6b9f9392331de721",
        },
        {
            "method": "DELETE",
            "host": "127.0.0.1:8085",
            "path": "/bucket/infinito-engine-check/xyz",
            "query": None,
            "payload": b"",
            "signature": "fb4f99e695b2c37135b9b2a92ebcb5436c6deabd9bd6e876cd6b5d4eae00b0b0",
        },
        {
            "method": "GET",
            "host": "host.example:8333",
            "path": "/b/k",
            "query": {"a": "1", "B": "2", "c": "x y"},
            "payload": b"body",
            "signature": "6cf8880d3c0baa47750aa5b0736a2b10459546b2f583643689200c01e067e8ec",
        },
    ]

    def _sign(self, vector: dict) -> dict[str, str]:
        from datetime import datetime

        return sigv4.sign(
            vector["method"],
            vector["host"],
            vector["path"],
            region=REGION,
            access_key=ACCESS_KEY,
            secret_key=SECRET_KEY,
            query=vector["query"],
            payload=vector["payload"],
            now=datetime(2013, 5, 24, tzinfo=UTC),
        )

    def test_signatures_match_the_reference_implementation(self) -> None:
        for vector in self.VECTORS:
            with self.subTest(method=vector["method"], path=vector["path"]):
                header = self._sign(vector)["Authorization"]
                self.assertEqual(
                    header.rsplit("Signature=", 1)[1],
                    vector["signature"],
                )

    def test_a_changed_secret_changes_the_signature(self) -> None:
        from datetime import datetime

        vector = self.VECTORS[0]
        other = sigv4.sign(
            vector["method"],
            vector["host"],
            vector["path"],
            region=REGION,
            access_key=ACCESS_KEY,
            secret_key=f"{SECRET_KEY}x",
            payload=vector["payload"],
            now=datetime(2013, 5, 24, tzinfo=UTC),
        )
        self.assertNotIn(vector["signature"], other["Authorization"])

    def test_a_space_encodes_as_percent_twenty_not_plus(self) -> None:
        self.assertEqual(sigv4.canonical_query({"c": "x y"}), "c=x%20y")

    def test_the_secret_never_appears_in_the_returned_headers(self) -> None:
        header_blob = "".join(self._sign(self.VECTORS[0]).values())
        self.assertNotIn(SECRET_KEY, header_blob)


if __name__ == "__main__":
    unittest.main()
