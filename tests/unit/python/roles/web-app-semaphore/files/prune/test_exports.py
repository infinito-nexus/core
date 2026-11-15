from __future__ import annotations

import contextlib
import datetime as dt
import html
import importlib
import io
import os
import tempfile
import unittest
import unittest.mock as mock
import urllib.parse
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding

from tests.utils.connect_proxy import ConnectProxy, direct_dials, recorded_dials
from tests.utils.openbao_stub import OpenBaoStub, make_ca
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.openbao_client import https_connection
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

servers = importlib.import_module(
    "tests.unit.python.roles.web-app-semaphore.files._export_servers"
)
prune = servers.load_task_module("prune/exports")
task = servers.load_task_module("export_task")

JWT = "prune-task-jwt"
BAO_TOKEN = "s.prune"
ACCESS_KEY = "export-access"
SECRET_KEY = "export-secret-key-0815"
NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)
AGES = {
    "ws-0a/1.tar": dt.timedelta(hours=2),
    "ws-0a/2.tar": dt.timedelta(minutes=90),
    "ws-0b/3 & 4.tar": dt.timedelta(minutes=61),
    "ws-0b/5.tar": dt.timedelta(minutes=60),
    "ws-0c/6.tar": dt.timedelta(minutes=59),
    "ws-0c/7.tar": dt.timedelta(minutes=1),
    "ws-0d/8.tar": dt.timedelta(hours=3),
}
OLD = sorted(key for key, age in AGES.items() if age > dt.timedelta(hours=1))
YOUNG = sorted(set(AGES) - set(OLD))


class Bucket:
    """
    Args:
        page: how many objects one listing page holds.
        refused: keys whose delete answers HTTP 500.
        now: the time the objects' ages count back from.
    """

    def __init__(self, page: int, refused: tuple[str, ...], now: dt.datetime) -> None:
        self.page = page
        self.refused = refused
        self.objects = {key: now - age for key, age in AGES.items()}
        self.listings: list[dict[str, str]] = []

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: Any
    ) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if not query.get("X-Amz-Signature") or not query.get(
            "X-Amz-Credential", ""
        ).startswith(f"{ACCESS_KEY}/"):
            return 403, b"unsigned"
        if method == "GET" and parts.path == "/exports":
            self.listings.append(query)
            return 200, self._page(int(query.get("continuation-token", "0")))
        key = urllib.parse.unquote(parts.path.removeprefix("/exports/"))
        if method != "DELETE" or key not in self.objects:
            return 404, b""
        if key in self.refused:
            return 500, b""
        del self.objects[key]
        return 204, b""

    def _page(self, start: int) -> bytes:
        keys = sorted(self.objects)[start : start + self.page]
        truncated = start + self.page < len(self.objects)
        contents = "".join(
            f"<Contents><Key>{html.escape(key)}</Key>"
            f"<LastModified>{self.objects[key]:%Y-%m-%dT%H:%M:%S}.000Z</LastModified>"
            "<Size>1</Size></Contents>"
            for key in keys
        )
        token = (
            f"<NextContinuationToken>{start + self.page}</NextContinuationToken>"
            if truncated
            else ""
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult>'
            f"<Name>exports</Name><IsTruncated>{str(truncated).lower()}</IsTruncated>"
            f"{token}{contents}</ListBucketResult>"
        ).encode()


class PruneCase(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = OpenBaoStub(
            tokens={BAO_TOKEN: ["platform/export/"]},
            logins={(prune.ROLE, JWT): BAO_TOKEN},
        )
        self.addCleanup(self.stub.close)
        self.stub.put(
            "platform/export/s3", {"access_key": ACCESS_KEY, "secret_key": SECRET_KEY}
        )
        self.bucket = Bucket(page=4, refused=(), now=NOW)
        self.env = {
            "SEMAPHORE_JWT": JWT,
            "BAO_ADDR": self.stub.addr,
            "BAO_CACERT": self.stub.cafile,
            "EXPORT_S3_ENDPOINT": "https://s3.example.org",
            "EXPORT_S3_REGION": "us-east-1",
        }

    def remaining(self) -> list[str]:
        return sorted(self.bucket.objects)


class TestThePrune(PruneCase):
    def test_only_objects_older_than_an_hour_go_across_both_pages(self) -> None:
        deleted, failures = prune.run(self.env, self.bucket, NOW)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(deleted), OLD)
        self.assertEqual(self.remaining(), YOUNG)
        self.assertEqual(YOUNG, ["ws-0b/5.tar", "ws-0c/6.tar", "ws-0c/7.tar"])
        self.assertEqual(
            [listing.get("continuation-token") for listing in self.bucket.listings],
            [None, "4"],
        )
        self.assertTrue(all(q["list-type"] == "2" for q in self.bucket.listings))

    def test_control_a_prune_that_reads_the_first_page_only_keeps_an_old_object(
        self,
    ) -> None:
        first_page = prune.listing

        with mock.patch.object(
            prune, "listing", lambda text: (first_page(text)[0], None)
        ):
            prune.run(self.env, self.bucket, NOW)
        self.assertEqual(self.remaining(), [*YOUNG, "ws-0d/8.tar"])

    def test_a_failed_delete_is_named_and_the_rest_still_go(self) -> None:
        self.bucket.refused = ("ws-0a/1.tar",)
        deleted, failures = prune.run(self.env, self.bucket, NOW)
        self.assertEqual(
            failures, ["ws-0a/1.tar: DELETE /exports/ws-0a/1.tar answered HTTP 500"]
        )
        self.assertEqual(sorted(deleted), [key for key in OLD if key != "ws-0a/1.tar"])

    def test_control_without_the_per_object_catch_the_rest_stays(self) -> None:
        self.bucket.refused = ("ws-0a/1.tar",)
        with (
            mock.patch.object(prune, "FAILURES", ()),
            self.assertRaises(task.ExportRefusedError),
        ):
            prune.run(self.env, self.bucket, NOW)
        self.assertIn("ws-0a/2.tar", self.remaining())

    def test_main_names_the_failed_delete_and_exits_non_zero(self) -> None:
        self.bucket.refused = ("ws-0b/3 & 4.tar",)
        code, stdout, stderr = self.main()
        self.assertEqual(code, 1)
        self.assertIn("prune exports failed: ws-0b/3 & 4.tar:", stderr)
        self.assertIn("prune exports: deleted ws-0a/1.tar", stdout)

    def test_no_secret_reaches_the_output(self) -> None:
        code, stdout, stderr = self.main()
        self.assertEqual(code, 0, stderr)
        for secret in (SECRET_KEY, JWT, BAO_TOKEN):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, stdout + stderr)

    def test_the_environment_of_the_scheduled_templates_supplies_every_name(
        self,
    ) -> None:
        variables = load_yaml_any(
            str(PROJECT_ROOT / "roles/web-app-semaphore" / ROLE_FILE_VARS_MAIN)
        )["SEMAPHORE_EXPORT_VARIABLES"]
        self.assertEqual(
            sorted(set(prune.REQUIRED_ENV) - set(variables)), ["SEMAPHORE_JWT"]
        )

    def test_a_truncated_listing_without_a_token_is_refused(self) -> None:
        with self.assertRaisesRegex(task.ExportRefusedError, "continuation token"):
            prune.listing("<IsTruncated>true</IsTruncated>")

    def main(self) -> tuple[int, str, str]:
        refused = self.bucket.refused
        self.bucket = Bucket(page=4, refused=refused, now=dt.datetime.now(dt.UTC))
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env),
            mock.patch.object(prune, "task_opener", lambda environ: self.bucket),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = prune.main([])
        return code, stdout.getvalue(), stderr.getvalue()


class TestThePruneBehindTheEgressProxy(PruneCase):
    def setUp(self) -> None:
        super().setUp()
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        ca_key, ca_cert = make_ca("prune test CA")
        bundle = directory / "bundle.pem"
        bundle.write_bytes(
            Path(self.stub.cafile).read_bytes()  # nocheck: cache-read tempdir
            + ca_cert.public_bytes(Encoding.PEM)
        )
        self.web = servers.HttpsApp(
            self.bucket, servers.server_context(directory, ca_key, ca_cert)
        )
        self.addCleanup(self.web.close)
        self.proxy = ConnectProxy()
        self.addCleanup(self.proxy.close)
        self.env.update(
            {
                "BAO_CACERT": str(bundle),
                "EXPORT_S3_ENDPOINT": f"https://{self.web.target}",
                task.PROXY_ENV: self.proxy.address,
            }
        )

    def proxied_run(self) -> list[str]:
        with recorded_dials() as dials:
            prune.run(self.env, task.task_opener(self.env), NOW)
        return dials

    def test_openbao_and_s3_go_through_the_tunnel(self) -> None:
        dials = self.proxied_run()
        self.assertEqual(direct_dials(dials, self.proxy.address), [])
        self.assertEqual(
            set(self.proxy.targets),
            {self.stub.addr.removeprefix("https://"), self.web.target},
        )
        self.assertEqual(self.remaining(), YOUNG)

    def test_negative_control_a_direct_https_request_beside_the_proxy_is_found(
        self,
    ) -> None:
        def direct(host, port, context, timeout, proxy=None):
            return https_connection(host, port, context, timeout)

        with mock.patch.object(task, "https_connection", direct):
            dials = self.proxied_run()
        self.assertEqual(
            set(direct_dials(dials, self.proxy.address)), {self.web.target}
        )


if __name__ == "__main__":
    unittest.main()
