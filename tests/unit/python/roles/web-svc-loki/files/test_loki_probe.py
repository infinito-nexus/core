import io
import json
import re
import sys
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout
from urllib.parse import parse_qsl, urlsplit

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
from utils.roles.swarm_loopback_reads import flattened, loopback_names, read_pattern

sys.path.insert(0, str(PROJECT_ROOT / "roles" / "web-svc-loki" / "files" / "test"))

import loki_probe

ROLE_DIR = PROJECT_ROOT / "roles" / "web-svc-loki"
ALERT = "CriticalApplicationLogLine"
APPLICATION = "loki-alert-1"
BASE = "http://loki:3100/loki/api/v1/query_range"


def _streams(*streams: list[str]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"application": "loki-canary"},
                    "values": [[str(i), line] for i, line in enumerate(lines)],
                }
                for lines in streams
            ],
        },
    }


def _vector(*samples: str) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1.0, sample]} for sample in samples],
        },
    }


def _ruler(state: str, name: str = ALERT, application: str = APPLICATION) -> dict:
    return {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "labels": {
                        "alertname": name,
                        "application": application,
                        "severity": "warning",
                    },
                    "annotations": {},
                    "state": state,
                    "activeAt": "2026-11-03T00:00:00Z",
                    "value": "1e+00",
                }
            ]
        },
    }


def _alertmanager(
    state: str, name: str = ALERT, application: str = APPLICATION
) -> list:
    return [
        {
            "labels": {"alertname": name, "application": application},
            "receivers": [{"name": "default"}],
            "status": {"state": state, "silencedBy": [], "inhibitedBy": []},
        }
    ]


def _function_body(script: str, name: str) -> str:
    """Body of the shell function *name* in *script*.

    Args:
        script: the shell script text.
        name: the function name.
    """
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}$", script, re.MULTILINE | re.DOTALL
    )
    if match is None:
        raise AssertionError(f"test.sh MUST define {name}()")
    return match.group(1)


def _run(argv: list[str], answer: object) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    stdin = io.StringIO(answer if isinstance(answer, str) else json.dumps(answer))
    with (
        mock.patch.object(sys, "stdin", stdin),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        status = loki_probe.main(argv)
    return status, stdout.getvalue(), stderr.getvalue()


class TestStoredLines(unittest.TestCase):
    def test_every_line_of_every_stream_is_listed_in_answer_order(self) -> None:
        self.assertEqual(
            ["a", "b", "c"], loki_probe.stored_lines(_streams(["a", "b"], ["c"]))
        )

    def test_an_answer_without_streams_lists_nothing(self) -> None:
        self.assertEqual([], loki_probe.stored_lines(_streams()))


class TestStoredCount(unittest.TestCase):
    def test_the_samples_of_the_vector_are_summed(self) -> None:
        self.assertEqual(20000, loki_probe.stored_count(_vector("19999", "1")))

    def test_an_empty_vector_counts_zero(self) -> None:
        self.assertEqual(0, loki_probe.stored_count(_vector()))

    def test_a_float_sample_is_read_as_its_integer(self) -> None:
        self.assertEqual(20000, loki_probe.stored_count(_vector("2e+04")))

    def test_a_streams_answer_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            loki_probe.stored_count(_streams(["a"]))


class TestRulerFiring(unittest.TestCase):
    def test_a_firing_alert_of_the_application_is_found(self) -> None:
        self.assertTrue(loki_probe.ruler_firing(_ruler("firing"), ALERT, APPLICATION))

    def test_a_pending_alert_is_not_firing(self) -> None:
        self.assertFalse(loki_probe.ruler_firing(_ruler("pending"), ALERT, APPLICATION))

    def test_the_alert_of_another_application_does_not_count(self) -> None:
        answer = _ruler("firing", application="loki-alert-2")
        self.assertFalse(loki_probe.ruler_firing(answer, ALERT, APPLICATION))

    def test_another_alert_of_the_application_does_not_count(self) -> None:
        answer = _ruler("firing", name="SomeOtherAlert")
        self.assertFalse(loki_probe.ruler_firing(answer, ALERT, APPLICATION))

    def test_no_alert_is_not_firing(self) -> None:
        answer = {"status": "success", "data": {"alerts": []}}
        self.assertFalse(loki_probe.ruler_firing(answer, ALERT, APPLICATION))


class TestAlertmanagerActive(unittest.TestCase):
    def test_an_active_alert_of_the_application_is_found(self) -> None:
        self.assertTrue(
            loki_probe.alertmanager_active(_alertmanager("active"), ALERT, APPLICATION)
        )

    def test_a_suppressed_alert_is_not_active(self) -> None:
        self.assertFalse(
            loki_probe.alertmanager_active(
                _alertmanager("suppressed"), ALERT, APPLICATION
            )
        )

    def test_the_alert_of_another_application_does_not_count(self) -> None:
        answer = _alertmanager("active", application="loki-alert-2")
        self.assertFalse(loki_probe.alertmanager_active(answer, ALERT, APPLICATION))

    def test_another_alert_of_the_application_does_not_count(self) -> None:
        answer = _alertmanager("active", name="SomeOtherAlert")
        self.assertFalse(loki_probe.alertmanager_active(answer, ALERT, APPLICATION))


class TestQueryUrl(unittest.TestCase):
    def test_every_reserved_character_of_a_logql_query_is_encoded(self) -> None:
        self.assertEqual(
            f"{BASE}?query=%7Bapplication%3D%22loki-canary%22%7D%20%7C%3D%20%22M%201%22",
            loki_probe.query_url(BASE, ['query={application="loki-canary"} |= "M 1"']),
        )

    def test_the_server_decodes_every_pair_back_in_order(self) -> None:
        pairs = [
            ("query", 'sum(count_over_time({source="journal"} |= "A+B&C=D" [1h]))'),
            ("start", "1"),
            ("end", "2"),
        ]
        url = loki_probe.query_url(BASE, [f"{key}={value}" for key, value in pairs])
        self.assertEqual(pairs, parse_qsl(urlsplit(url).query, strict_parsing=True))

    def test_without_pairs_the_base_is_returned_unchanged(self) -> None:
        self.assertEqual(BASE, loki_probe.query_url(BASE, []))

    def test_a_pair_without_an_equals_sign_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            loki_probe.query_url(BASE, ["limit"])


class TestAlertLine(unittest.TestCase):
    def test_the_line_carries_the_run_id(self) -> None:
        self.assertIn("1234", loki_probe.ALERT_LINE.format(run_id="1234"))

    def test_the_shipped_critical_pattern_matches_the_line(self) -> None:
        services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        pattern = services["loki"]["alerting"]["critical_pattern"]
        self.assertRegex(loki_probe.ALERT_LINE.format(run_id="1234"), pattern)


class TestMain(unittest.TestCase):
    def test_count_prints_the_sum(self) -> None:
        self.assertEqual((0, "20000\n", ""), _run(["count"], _vector("20000")))

    def test_lines_prints_one_line_each(self) -> None:
        self.assertEqual((0, "a\nb\n", ""), _run(["lines"], _streams(["a", "b"])))

    def test_firing_exits_zero_when_the_alert_fires(self) -> None:
        status, _, _ = _run(["firing", ALERT, APPLICATION], _ruler("firing"))
        self.assertEqual(0, status)

    def test_firing_exits_one_while_the_alert_is_pending(self) -> None:
        status, _, _ = _run(["firing", ALERT, APPLICATION], _ruler("pending"))
        self.assertEqual(1, status)

    def test_delivered_exits_zero_for_an_active_alert(self) -> None:
        status, _, _ = _run(["delivered", ALERT, APPLICATION], _alertmanager("active"))
        self.assertEqual(0, status)

    def test_delivered_exits_one_without_the_alert(self) -> None:
        status, _, _ = _run(["delivered", ALERT, APPLICATION], [])
        self.assertEqual(1, status)

    def test_alert_line_prints_the_line_without_reading_an_answer(self) -> None:
        self.assertEqual(
            (0, loki_probe.ALERT_LINE.format(run_id="7") + "\n", ""),
            _run(["alert-line", "7"], ""),
        )

    def test_url_prints_the_encoded_url_without_reading_an_answer(self) -> None:
        self.assertEqual(
            (0, f"{BASE}?limit=20\n", ""), _run(["url", BASE, "limit=20"], "")
        )

    def test_url_with_a_pair_without_an_equals_sign_exits_two(self) -> None:
        status, stdout, stderr = _run(["url", BASE, "limit"], "")
        self.assertEqual((2, ""), (status, stdout))
        self.assertIn("expected KEY=VALUE", stderr)

    def test_an_answer_that_is_not_json_exits_two(self) -> None:
        status, stdout, stderr = _run(["count"], "<html>502</html>")
        self.assertEqual((2, ""), (status, stdout))
        self.assertIn("unexpected answer", stderr)

    def test_an_answer_of_the_wrong_shape_exits_two(self) -> None:
        status, _, _ = _run(["firing", ALERT, APPLICATION], {"status": "error"})
        self.assertEqual(2, status)

    def test_an_unknown_command_exits_two(self) -> None:
        status, _, stderr = _run(["drop"], {})
        self.assertEqual(2, status)
        self.assertIn("unknown command", stderr)

    def test_a_missing_argument_exits_two(self) -> None:
        status, _, stderr = _run(["firing", ALERT], _ruler("firing"))
        self.assertEqual(2, status)
        self.assertIn("takes 2 arguments", stderr)


class TestCliTestScript(unittest.TestCase):
    def test_the_burst_writes_20000_lines_from_one_container(self) -> None:
        script = read_text(str(ROLE_DIR / "files" / "test" / "test.sh"))
        match = re.search(r"^burst_lines=(\d+)$", script, re.MULTILINE)
        self.assertIsNotNone(match, "test.sh MUST set burst_lines")
        self.assertEqual("20000", match.group(1))

    def test_loki_is_queried_from_a_container_on_its_network(self) -> None:
        script = read_text(str(ROLE_DIR / "files" / "test" / "test.sh"))
        self.assertIn(
            'network_get "${LOKI_TEST_NETWORK}"',
            _function_body(script, "loki_get"),
            "swarm publishes no local port, so the test MUST query Loki by "
            "service name from a container on the loki network",
        )
        self.assertIn('--network "${network}"', _function_body(script, "network_get"))

    def test_the_env_template_reads_no_loopback_port(self) -> None:
        values = flattened(load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
        pattern = read_pattern(loopback_names(values))
        template = read_text(str(ROLE_DIR / "templates" / "test.env.j2"))
        self.assertEqual(
            [],
            [line for line in template.splitlines() if pattern.search(line)],
            "swarm publishes no local port, so the CLI test MUST NOT reach "
            "Loki through one",
        )


if __name__ == "__main__":
    unittest.main()
