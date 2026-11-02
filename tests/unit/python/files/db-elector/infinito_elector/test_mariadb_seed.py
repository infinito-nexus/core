from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from infinito_elector_src.mariadb_seed import (
    Donor,
    backup_argv,
    request_seed,
    seed_position,
    token,
    verify,
)

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src

SECRET = b"seed-secret"
PEER = "10.0.9.7"


def _request(host: str = "m3", stamp: int = 1000, **extra) -> bytes:
    return json.dumps(
        {"host": host, "stamp": stamp, "token": token(SECRET, host, stamp), **extra}
    ).encode()


class FakeProcess:
    def __init__(self, argv, **kwargs) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.stdout = self
        self.done = False

    def poll(self):
        return 0 if self.done else None

    def close(self) -> None:
        return


class FakeRole:
    def __init__(self, kind: str | None) -> None:
        self.kind = kind

    def donor_kind(self) -> str | None:
        return self.kind


class TestToken(unittest.TestCase):
    def test_a_fresh_signed_request_names_its_host(self) -> None:
        self.assertEqual(verify(SECRET, json.loads(_request()), 1030), "m3")

    def test_a_stale_request_is_refused(self) -> None:
        self.assertIsNone(verify(SECRET, json.loads(_request()), 1061))

    def test_a_wrong_secret_is_refused(self) -> None:
        self.assertIsNone(verify(b"other", json.loads(_request()), 1000))

    def test_a_malformed_request_is_refused(self) -> None:
        self.assertIsNone(verify(SECRET, ["m3"], 1000))


class TestDonor(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.secret_file = Path(self.scratch.name) / "secret"
        self.secret_file.write_bytes(SECRET + b"\n")
        self.started: list[FakeProcess] = []

    def tearDown(self) -> None:
        self.scratch.cleanup()

    def _donor(self, kind: str | None) -> Donor:
        def popen(argv, **kwargs):
            process = FakeProcess(argv, **kwargs)
            self.started.append(process)
            return process

        return Donor(
            role=FakeRole(kind),
            secret_file=str(self.secret_file),
            seed_port=4444,
            seed_relay="/opt/db-elector/seed_relay.py",
            user="mysql",
            socket="/run/mysqld/mysqld.sock",
            popen=popen,
            clock=lambda: 1000.0,
        )

    def test_a_replica_streams_its_backup_to_the_requesters_address(self) -> None:
        self.assertEqual(self._donor("replica").handle(_request(), PEER), 202)
        backup, relay = self.started
        self.assertIn("--slave-info", backup.argv)
        self.assertEqual(relay.argv[2:5], ["send", PEER, "4444"])
        self.assertIs(relay.kwargs["stdin"], backup)

    def test_a_second_request_waits_for_the_running_stream(self) -> None:
        donor = self._donor("replica")
        donor.handle(_request(stamp=1000), PEER)
        self.assertEqual(donor.handle(_request(stamp=1001), PEER), 409)
        for process in self.started:
            process.done = True
        self.assertEqual(donor.handle(_request(stamp=1001), PEER), 202)

    def test_a_request_that_started_a_stream_cannot_be_replayed(self) -> None:
        donor = self._donor("replica")
        self.assertEqual(donor.handle(_request(), PEER), 202)
        for process in self.started:
            process.done = True
        self.assertEqual(donor.handle(_request(), "10.0.9.66"), 403)
        self.assertEqual(len(self.started), 2)

    def test_the_writer_declines_a_replica_only_request(self) -> None:
        self.assertEqual(
            self._donor("writer").handle(_request(replica_only=True), PEER), 409
        )
        self.assertEqual(self._donor("writer").handle(_request(), PEER), 202)

    def test_an_unhealthy_instance_never_donates(self) -> None:
        self.assertEqual(self._donor(None).handle(_request(), PEER), 409)
        self.assertEqual(self.started, [])

    def test_an_unsigned_request_is_forbidden(self) -> None:
        self.assertEqual(self._donor("replica").handle(b'{"host": "m3"}', PEER), 403)
        self.assertEqual(self._donor("replica").handle(b"{", PEER), 400)


class TestRequest(unittest.TestCase):
    def test_replicas_are_asked_before_the_writer(self) -> None:
        asked: list[tuple[str, bool]] = []

        def post(url: str, body: bytes) -> int:
            replica_only = json.loads(body)["replica_only"]
            asked.append((url, replica_only))
            return (
                202 if url.startswith("http://mariadb-m1") and not replica_only else 409
            )

        donor = request_seed(
            host_id="m3",
            peers=["m1", "m2", "m3"],
            address=lambda host: f"mariadb-{host}",
            port=8008,
            secret=SECRET,
            post=post,
            clock=lambda: 1000.0,
        )
        self.assertEqual(donor, "m1")
        self.assertEqual(
            asked,
            [
                ("http://mariadb-m1:8008/seed", True),
                ("http://mariadb-m2:8008/seed", True),
                ("http://mariadb-m1:8008/seed", False),
            ],
        )

    def test_no_donor_returns_none(self) -> None:
        self.assertIsNone(
            request_seed(
                host_id="m3",
                peers=["m3"],
                address=str,
                port=1,
                secret=SECRET,
                post=lambda *_: 202,
            )
        )


class TestSeedPosition(unittest.TestCase):
    def test_reads_the_gtid_field(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as info:
            info.write("mariadb-bin.000003\t385\t0-7-42\n")
        self.assertEqual(seed_position(info.name), "0-7-42")
        Path(info.name).unlink()

    def test_backup_of_a_writer_records_no_slave_info(self) -> None:
        self.assertNotIn("--slave-info", backup_argv("mysql", "/s", replica=False))


if __name__ == "__main__":
    unittest.main()
