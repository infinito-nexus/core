from __future__ import annotations

import datetime as dt
import json
import unittest
import unittest.mock as mock
import urllib.parse
from typing import Any

from ._export_servers import load_task_module

task = load_task_module("export_task")

AWS_EXAMPLE = {
    "access_key": "AKIAIOSFODNN7EXAMPLE",
    "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}
AWS_EXAMPLE_SIGNATURE = (
    "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
)
AWS_EXAMPLE_TIME = dt.datetime(2013, 5, 24, tzinfo=dt.UTC)
PATH = task.membership_path("o-1", "g-owner", "u-1")
NOW_MS = 1_800_000_000_000
ENV = {
    "EXPORT_KEYCLOAK_URL": "https://auth.example.org/",
    "EXPORT_KEYCLOAK_REALM": "main",
}


class Opener:
    """
    Args:
        answers: the status and body each request answers, in order.
    """

    def __init__(self, answers: list[tuple[int, bytes]]) -> None:
        self.answers = answers
        self.requests: list[tuple[str, str]] = []

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: Any
    ) -> tuple[int, bytes]:
        self.requests.append((method, url))
        return self.answers.pop(0)


def membership(operation: str, time: int, path: str) -> dict[str, Any]:
    return {
        "resourceType": task.MEMBERSHIP_TYPE,
        "resourcePath": path,
        "operationType": operation,
        "time": time,
    }


def export_task(opener: Opener) -> Any:
    return task.ExportTask(ENV, tuple(ENV), opener, mock.Mock(spec=task.OpenBaoClient))


class TestPresign(unittest.TestCase):
    def test_the_aws_documented_presigned_url_signs_alike(self) -> None:
        url = task.presign(
            "GET",
            "https://examplebucket.s3.amazonaws.com/test.txt",
            AWS_EXAMPLE,
            "us-east-1",
            AWS_EXAMPLE_TIME,
            86400,
            {},
        )
        self.assertTrue(url.endswith(f"&X-Amz-Signature={AWS_EXAMPLE_SIGNATURE}"), url)
        self.assertIn(
            "X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2F"
            "aws4_request",
            url,
        )

    def test_a_request_parameter_is_carried_and_signed(self) -> None:
        def signed(query: dict[str, str]) -> dict[str, str]:
            url = task.presign(
                "GET",
                "https://s3.example.org/exports",
                AWS_EXAMPLE,
                "us-east-1",
                AWS_EXAMPLE_TIME,
                60,
                query,
            )
            return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))

        listing = signed({"list-type": "2"})
        self.assertEqual(listing["list-type"], "2")
        self.assertNotEqual(listing["X-Amz-Signature"], signed({})["X-Amz-Signature"])


class TestReason(unittest.TestCase):
    def test_a_refusal_keeps_its_message(self) -> None:
        self.assertEqual(task.reason(task.ExportRefusedError("no owner")), "no owner")

    def test_an_os_error_names_only_its_type(self) -> None:
        self.assertEqual(task.reason(OSError("GET /x?token=secret")), "OSError")


class TestRecentJoin(unittest.TestCase):
    def test_a_young_create_answers_its_time(self) -> None:
        joined = NOW_MS - task.DAY_MS
        events = [membership("CREATE", joined, PATH)]
        self.assertEqual(task.recent_join(events, PATH, NOW_MS, 7), joined)

    def test_a_create_at_the_minimum_age_is_old_enough(self) -> None:
        events = [membership("CREATE", NOW_MS - 7 * task.DAY_MS, PATH)]
        self.assertIsNone(task.recent_join(events, PATH, NOW_MS, 7))

    def test_a_delete_after_the_create_answers_none(self) -> None:
        events = [
            membership("CREATE", NOW_MS - 2 * task.DAY_MS, PATH),
            membership("DELETE", NOW_MS - task.DAY_MS, PATH),
        ]
        self.assertIsNone(task.recent_join(events, PATH, NOW_MS, 7))

    def test_an_event_of_another_path_never_counts(self) -> None:
        events = [membership("CREATE", NOW_MS - task.DAY_MS, f"{PATH}x")]
        self.assertIsNone(task.recent_join(events, PATH, NOW_MS, 7))


class TestExportTask(unittest.TestCase):
    def test_a_missing_name_is_refused_before_any_request(self) -> None:
        opener = Opener([])
        with self.assertRaisesRegex(task.ExportRefusedError, "EXPORT_S3_REGION"):
            task.ExportTask(
                ENV,
                (*ENV, "EXPORT_S3_REGION"),
                opener,
                mock.Mock(spec=task.OpenBaoClient),
            )
        self.assertEqual(opener.requests, [])

    def test_a_failed_request_names_its_path_but_never_its_query(self) -> None:
        with self.assertRaises(task.ExportRefusedError) as raised:
            export_task(Opener([(403, b"")]))._call(
                "GET", "https://s3.example.org/exports?X-Amz-Signature=abc", None, {}
            )
        self.assertEqual(str(raised.exception), "GET /exports answered HTTP 403")

    def test_the_organization_is_found_by_its_exact_workspace_marker(self) -> None:
        opener = Opener([(200, json.dumps([{"id": 42}]).encode())])
        self.assertEqual(export_task(opener).organization("ws-1"), "42")
        url = urllib.parse.urlsplit(opener.requests[0][1])
        self.assertEqual(url.path, "/admin/realms/main/organizations")
        self.assertEqual(
            dict(urllib.parse.parse_qsl(url.query)),
            {"q": "workspace.id:ws-1", "exact": "true"},
        )

    def test_no_single_organization_is_refused(self) -> None:
        for found in ([], [{"id": 1}, {"id": 2}]):
            with self.subTest(found=found):
                opener = Opener([(200, json.dumps(found).encode())])
                with self.assertRaisesRegex(task.ExportRefusedError, "no single"):
                    export_task(opener).organization("ws-1")


class TestHttpsOpener(unittest.TestCase):
    def test_a_plain_http_url_is_refused_without_a_connection(self) -> None:
        connect = mock.Mock()
        with mock.patch.object(task, "https_connection", connect):
            send = task.https_opener(mock.Mock(), None)
            with self.assertRaisesRegex(task.ExportRefusedError, "no https"):
                send("GET", "http://s3.example.org/exports", None, {})
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
