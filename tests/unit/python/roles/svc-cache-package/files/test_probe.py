from __future__ import annotations

import importlib.util
import os
import unittest
import unittest.mock as mock

from utils.cache.files import read_text
from utils.cache.render import upstreams_conf
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/svc-cache-package"
MODULE_PATH = ROLE_DIR / "files/test/probe.py"
MARKER = load_yaml(ROLE_DIR / ROLE_FILE_VARS_MAIN)["CACHE_PACKAGE_BACKEND_MARKER"]

ENV = {
    "CACHE_PACKAGE_TEST_BACKEND_MARKER": MARKER,
    "CACHE_PACKAGE_TEST_CERTS_DIR": "/etc/nginx/certs",
    "CACHE_PACKAGE_TEST_CONTAINER": "package-cache",
    "CACHE_PACKAGE_TEST_FRONTEND": "package-cache-frontend",
    "CACHE_PACKAGE_TEST_HOSTS": "[]",
    "CACHE_PACKAGE_TEST_PORT": "8081",
    "CACHE_PACKAGE_TEST_REPOS": "{}",
}

spec = importlib.util.spec_from_file_location("cache_package_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(spec)
with mock.patch.dict(os.environ, ENV):
    spec.loader.exec_module(probe)

TARGET = "registry.ollama.ai/ on port 443"
REPO = "raw-ollama-registry"
UNREACHED = f"did not reach repository {REPO}"
UPSTREAM_UNREACHED = f"Nexus could not reach upstream for repository {REPO}"


def head(status: str, timing: str | None, marker: str = MARKER) -> str:
    lines = [f"HTTP/1.1 {status}", "Server: nginx/1.31.0", "Content-Type: text/html"]
    if timing is not None:
        lines.append(f"{marker}: {timing}")
    return "\r\n".join(lines) + "\r\n"


def verdict(text: str) -> str:
    return probe.proxied_verdict(TARGET, REPO, text, MARKER)


class TestNexusAnswered(unittest.TestCase):
    def test_an_upstream_503_relayed_by_nexus_passes(self) -> None:
        self.assertEqual(
            verdict(head("503 Service Unavailable", "0.412")),
            "",
            "registry.ollama.ai answers 503 on its root and Nexus relays it; "
            "that is the upstream's answer, not the frontend's",
        )

    def test_a_nexus_404_passes(self) -> None:
        self.assertEqual(verdict(head("404 Not Found", "0.003")), "")

    def test_a_mirror_sibling_that_answered_passes(self) -> None:
        self.assertEqual(verdict(head("200 OK", "0.008 : 0.031")), "")

    def test_a_mirror_sibling_answering_after_an_unreachable_primary_passes(
        self,
    ) -> None:
        self.assertEqual(verdict(head("200 OK", "- : 0.031")), "")

    def test_a_second_peer_that_answered_passes(self) -> None:
        self.assertEqual(verdict(head("200 OK", "-, 0.012")), "")


class TestNexusCouldNotReachUpstream(unittest.TestCase):
    def test_a_nexus_502_fails(self) -> None:
        failure = verdict(head("502 Bad Gateway", "0.087"))
        self.assertIn(UPSTREAM_UNREACHED, failure)
        self.assertNotIn(UNREACHED, failure)

    def test_a_mirror_whose_sibling_also_answered_502_fails(self) -> None:
        self.assertIn(
            UPSTREAM_UNREACHED, verdict(head("502 Bad Gateway", "0.008 : 0.031"))
        )


class TestNginxDidNotReachNexus(unittest.TestCase):
    def test_a_refused_connection_to_nexus_fails(self) -> None:
        failure = verdict(head("502 Bad Gateway", "-"))
        self.assertIn(UNREACHED, failure)
        self.assertIn("'502'", failure)

    def test_a_timed_out_nexus_fails(self) -> None:
        self.assertIn(UNREACHED, verdict(head("504 Gateway Time-out", "-")))

    def test_a_mirror_whose_sibling_got_no_answer_fails(self) -> None:
        self.assertIn(
            UNREACHED,
            verdict(head("502 Bad Gateway", "0.008 : -")),
            "the client sees the response of the last attempt, so an earlier "
            "Nexus answer that was intercepted proves nothing",
        )

    def test_no_response_from_the_frontend_fails(self) -> None:
        failure = verdict("")
        self.assertIn(UNREACHED, failure)
        self.assertIn("answered ''", failure)


class TestNegativeControl(unittest.TestCase):
    def test_the_ci_failure_status_without_the_marker_still_fails(self) -> None:
        self.assertIn(
            UNREACHED,
            verdict(head("503 Service Unavailable", None)),
            "a frontend that dropped the marker must fail instead of passing "
            "on a status the probe can no longer attribute",
        )

    def test_nginxs_own_502_is_not_blamed_on_upstream(self) -> None:
        failure = verdict(head("502 Bad Gateway", "-"))
        self.assertIn(UNREACHED, failure)
        self.assertNotIn(UPSTREAM_UNREACHED, failure)

    def test_a_502_without_the_marker_is_not_blamed_on_upstream(self) -> None:
        failure = verdict(head("502 Bad Gateway", None))
        self.assertIn(UNREACHED, failure)
        self.assertNotIn(UPSTREAM_UNREACHED, failure)

    def test_an_upstream_5xx_nexus_relays_as_503_is_not_a_502(self) -> None:
        self.assertEqual(verdict(head("503 Service Unavailable", "0.412")), "")

    def test_a_200_without_the_marker_fails(self) -> None:
        self.assertIn(UNREACHED, verdict(head("200 OK", None)))

    def test_a_marker_under_another_name_is_not_read(self) -> None:
        self.assertIn(
            UNREACHED,
            verdict(head("503 Service Unavailable", "0.412", marker="X-Other")),
        )

    def test_an_interim_response_does_not_lend_its_headers(self) -> None:
        text = (
            f"HTTP/1.1 100 Continue\r\n{MARKER}: 0.001\r\n\r\n"
            f"{head('502 Bad Gateway', '-')}"
        )
        self.assertIn(UNREACHED, verdict(text))


class TestParseHead(unittest.TestCase):
    def test_header_names_are_matched_case_insensitively(self) -> None:
        text = f"HTTP/2 503\r\n{MARKER.lower()}: 0.2\r\n"
        self.assertEqual(verdict(text), "")

    def test_the_final_response_wins(self) -> None:
        text = f"HTTP/1.1 100 Continue\r\n\r\n{head('503 Service Unavailable', '0.2')}"
        code, headers = probe.parse_head(text)
        self.assertEqual(code, "503")
        self.assertEqual(headers[MARKER.lower()], "0.2")


class TestFrontendContract(unittest.TestCase):
    LINE = f"add_header {MARKER} $upstream_header_time always;"

    def setUp(self) -> None:
        self.lines = [line.strip() for line in upstreams_conf().splitlines()]

    def test_the_frontend_emits_the_marker(self) -> None:
        self.assertIn(
            self.LINE,
            self.lines,
            "without 'always' nginx adds the header to 2xx and 3xx only, so "
            "the 5xx the probe has to attribute would carry no marker",
        )

    def test_the_marker_is_set_above_every_server_block(self) -> None:
        first_server = next(
            index for index, line in enumerate(self.lines) if line == "server {"
        )
        self.assertLess(self.lines.index(self.LINE), first_server)

    def test_no_block_sets_its_own_add_header(self) -> None:
        self.assertEqual(
            [line for line in self.lines if line.startswith("add_header")],
            [self.LINE],
            "a server or location with its own add_header drops the inherited "
            "marker, and the probe would fail every host behind it",
        )

    def test_the_probe_is_handed_the_marker_the_role_declares(self) -> None:
        env = read_text(str(ROLE_DIR / "templates/test.env.j2"))
        self.assertIn(
            "CACHE_PACKAGE_TEST_BACKEND_MARKER={{ CACHE_PACKAGE_BACKEND_MARKER }}",
            env.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
