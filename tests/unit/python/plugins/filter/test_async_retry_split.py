import unittest

from plugins.filter.async_failures import async_retry_split
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

from . import PROJECT_ROOT

_DEFAULTS = (
    PROJECT_ROOT / "roles" / "sys-dns-cloudflare-records" / ROLE_FILE_DEFAULTS_MAIN
)
_ROLE = load_yaml(str(_DEFAULTS))
_TOLERATE = _ROLE["cloudflare_tolerate"]
_TRANSIENT = _ROLE["cloudflare_transient"]

_ERP = {"zone": "example.org", "type": "AAAA", "name": "*.erp", "content": "::1"}


def _reaped(**job):
    fired = {"ansible_loop_var": "item", "item": _ERP, "ansible_job_id": "j1.1"}
    return {"ansible_loop_var": "item", "item": fired, "ansible_job_id": "j1.1", **job}


def _split(*results):
    return async_retry_split(list(results), _TOLERATE, _TRANSIENT)


class TestAsyncRetrySplit(unittest.TestCase):
    def test_a_job_that_never_finished_is_retried_and_names_its_record(self):
        split = _split(_reaped(started=True, finished=False))
        self.assertEqual([], split["failed"])
        self.assertEqual(
            [{"item": _ERP, "error": "job did not finish"}], split["retry"]
        )

    def test_an_attempt_killed_on_its_timeout_is_retried(self):
        split = _split(_reaped(finished=True, failed=True, msg="Timeout exceeded"))
        self.assertEqual(["Timeout exceeded"], [r["error"] for r in split["retry"]])

    def test_connection_errors_rate_limits_and_5xx_are_retried(self):
        messages = [
            "Failed API call /zones?name=example.org; got unexpected HTTP code -1: Connection failure: timed out",
            "Failed API call /zones/z/dns_records; got unexpected HTTP code 502: Bad Gateway",
            "API client is rate limited; Status: 429; Method: GET: Call: /zones",
            "async task did not complete within the requested time - 60s",
        ]
        split = _split(*(_reaped(finished=True, failed=True, msg=m) for m in messages))
        self.assertEqual([], split["failed"])
        self.assertEqual(messages, [r["error"] for r in split["retry"]])

    def test_a_4xx_or_auth_error_fails_at_once_without_a_retry(self):
        messages = [
            "API bad request; Status: 400; Method: POST: Call: /zones/z/dns_records; Error details: code: 9005, error: Content for AAAA record is invalid.; ",
            "API user does not have permission; Status: 401; Method: GET: Call: /zones",
            "API request not authenticated; Status: 403; Method: GET: Call: /zones",
            "Failed API call /zones/z/dns_records; got unexpected HTTP code 404: Not Found",
        ]
        split = _split(*(_reaped(finished=True, failed=True, msg=m) for m in messages))
        self.assertEqual([], split["retry"])
        self.assertEqual(
            [m.strip() for m in messages], [f["error"] for f in split["failed"]]
        )
        self.assertTrue(all(f["item"] is _ERP for f in split["failed"]))

    def test_an_identical_record_is_success_not_a_retry(self):
        split = _split(
            _reaped(
                finished=True,
                failed=True,
                msg="API bad request; Status: 400; Error details: code: 81058, error: An identical record already exists.; ",
            )
        )
        self.assertEqual({"retry": [], "failed": []}, split)

    def test_a_zone_id_containing_81058_never_passes_a_4xx_as_success(self):
        msg = "API bad request; Status: 400; Method: POST: Call: /zones/a81058b/dns_records; Error details: code: 9005, error: bad"
        split = _split(_reaped(finished=True, failed=True, msg=msg))
        self.assertEqual([msg], [f["error"] for f in split["failed"]])

    def test_a_job_file_not_yet_written_is_retried(self):
        split = _split(_reaped(finished=True, failed=True, msg="could not find job"))
        self.assertEqual(["could not find job"], [r["error"] for r in split["retry"]])

    def test_an_unreadable_job_fails_and_is_not_retried(self):
        split = _split(_reaped(finished=True, failed_when_suppressed_exception="x"))
        self.assertEqual([], split["retry"])
        self.assertEqual(1, len(split["failed"]))

    def test_a_result_polled_in_place_names_its_record_too(self):
        polled = {
            "ansible_loop_var": "item",
            "item": _ERP,
            "ansible_job_id": "j2.2",
            "finished": True,
            "failed": True,
            "msg": "Timeout exceeded",
        }
        self.assertEqual(_ERP, _split(polled)["retry"][0]["item"])

    def test_finished_jobs_and_empty_input_need_nothing(self):
        self.assertEqual(
            {"retry": [], "failed": []}, _split(_reaped(finished=True, changed=False))
        )
        self.assertEqual(
            {"retry": [], "failed": []}, async_retry_split(None, None, None)
        )

    def test_a_hang_on_every_attempt_ends_with_the_record_named(self):
        pending = [_ERP]
        last = []
        for _attempt in range(int(_ROLE["cloudflare_attempts"])):
            if not pending:
                break
            split = _split(*(_reaped(started=True, finished=False) for _ in pending))
            self.assertEqual([], split["failed"])
            last = split["retry"]
            pending = [r["item"] for r in last]
        self.assertEqual([{"item": _ERP, "error": "job did not finish"}], last)


if __name__ == "__main__":
    unittest.main()
