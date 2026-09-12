import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_str
from utils.docker.healthcheck.compose import build, compose, resolve_flavors
from utils.docker.healthcheck.prefixes import PREFIXES
from utils.docker.healthcheck.probes import PROBES, Connect, Curl, HttpStatus, Nc, Tcp

_MARKER = "/tmp/email_sent"


def probe(flavor, **context):
    return compose(flavor, **context).test()


def run_probe(argv, *, msmtp_rc, curl_rc):
    """Execute a CMD-SHELL probe against stubbed msmtp and curl.

    Args:
        argv: the probe as returned by :func:`probe`.
        msmtp_rc: exit code the msmtp stub returns.
        curl_rc: exit code the curl stub returns.

    Returns:
        ``(exit_code, marker_written)`` for the probe as the container runs it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stubs = root / "bin"
        stubs.mkdir()
        for name, rc in (("msmtp", msmtp_rc), ("curl", curl_rc)):
            stub = stubs / name
            stub.write_text(f"#!/bin/sh\ncat >/dev/null 2>&1\nexit {rc}\n")
            stub.chmod(0o755)
        marker = root / "email_sent"
        script = argv[1].replace(_MARKER, str(marker))
        completed = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            check=False,
        )
        return completed.returncode, marker.exists()


def block(flavor, overrides=None, **context):
    return load_yaml_str(build(flavor, overrides or {}, **context))["healthcheck"]


class TestCurl(unittest.TestCase):
    def test_single_sample_uses_the_exec_form(self):
        self.assertEqual(
            ["CMD", "curl", "-f", "--noproxy", "*", "http://127.0.0.1:80/"],
            probe("curl", port=80, path="", hostname=None, samples=1),
        )

    def test_an_empty_port_is_left_out_of_the_url(self):
        self.assertEqual("http://127.0.0.1/", probe("curl", port="")[-1])

    def test_the_path_is_appended_without_a_second_slash(self):
        self.assertEqual(
            "http://127.0.0.1:80/health/ready",
            probe("curl", port=80, path="health/ready")[-1],
        )

    def test_a_hostname_becomes_a_header_argument(self):
        self.assertEqual(
            [
                "CMD",
                "curl",
                "-f",
                "--noproxy",
                "*",
                "-H",
                "Host: app.example",
                "http://127.0.0.1:80/",
            ],
            probe("curl", port=80, hostname="app.example"),
        )

    def test_sampling_chains_one_request_per_replica_in_a_single_probe(self):
        """retries counts consecutive failures, so a streak cannot see (N-1)/N loss."""
        chained = probe("curl", port=80, samples=3)
        self.assertEqual("CMD-SHELL", chained[0])
        self.assertEqual(3, chained[1].count("curl -f"))

    def test_sampling_keeps_the_host_header(self):
        self.assertIn(
            "-H 'Host: a.example'",
            probe("curl", port=80, hostname="a.example", samples=2)[1],
        )


class TestOtherFlavors(unittest.TestCase):
    def test_wget_spiders_the_url_with_the_proxy_off(self):
        self.assertEqual(
            ["CMD", "wget", "--spider", "--proxy=off", "http://127.0.0.1:8080/ready"],
            probe("wget", port=8080, path="ready"),
        )

    def test_http_falls_back_from_wget_to_curl(self):
        self.assertEqual(
            [
                "CMD-SHELL",
                (
                    "wget -qO- http://127.0.0.1:8080/ >/dev/null "
                    "|| curl -fsS --noproxy '*' http://127.0.0.1:8080/ >/dev/null"
                ),
            ],
            probe("http", port=8080),
        )

    def test_nc_probes_the_port_only(self):
        self.assertEqual(
            ["CMD-SHELL", "nc -z localhost 5432 || exit 1"], probe("nc", port=5432)
        )

    def test_tcp_speaks_http_over_a_bash_socket(self):
        argv = probe("tcp", port=8080, path="")
        self.assertEqual(["CMD", "bash", "-c"], argv[:3])
        self.assertIn("exec 3<>/dev/tcp/localhost/8080", argv[3])
        self.assertIn("grep -q 'HTTP/1'", argv[3])

    def test_tcp_keeps_the_escapes_the_shell_needs(self):
        """echo -e must receive backslash escapes, not real newlines."""
        self.assertIn("\\r\\n", probe("tcp", port=80)[3])

    def test_http_status_demands_a_2xx_or_3xx_status_line(self):
        argv = probe("http_status", port=80, path="health")
        self.assertIn("GET /health HTTP/1.1", argv[3])
        self.assertIn("[23][0-9][0-9]", argv[3])

    def test_msmtp_curl_sends_one_mail_and_then_only_probes(self):
        argv = probe(
            "msmtp_curl",
            port=80,
            email_enabled=True,
            domain="app.example",
            blackhole="void@example",
        )
        self.assertIn("if [ ! -f /tmp/email_sent ]", argv[1])
        self.assertIn("msmtp --domain=app.example -t void@example", argv[1])
        self.assertTrue(
            argv[1].endswith("curl -f --noproxy '*' http://127.0.0.1:80/ || exit 1")
        )

    def test_the_ehlo_identity_is_named_so_a_strict_relay_accepts_it(self):
        """msmtp defaults EHLO to "localhost", which Stalwart answers with 550."""
        argv = probe(
            "msmtp_curl",
            port=80,
            email_enabled=True,
            domain="app.example",
            blackhole="void@example",
        )
        self.assertIn("--domain=app.example", argv[1])

    def test_without_a_domain_no_empty_ehlo_flag_is_emitted(self):
        argv = probe(
            "msmtp_curl",
            port=80,
            email_enabled=True,
            domain="",
            blackhole="void@example",
        )
        self.assertNotIn("--domain=", argv[1])
        self.assertIn("msmtp -t void@example", argv[1])

    def test_msmtp_curl_probe_behaviour(self):
        argv = probe(
            "msmtp_curl",
            port=80,
            email_enabled=True,
            domain="app.example",
            blackhole="void@example",
        )
        cases = (
            ("a refused mail leaves the app healthy and retryable", 69, 0, 0, False),
            ("an accepted mail marks itself sent", 0, 0, 0, True),
            ("a dead web server is unhealthy", 0, 1, 1, None),
        )
        for label, msmtp_rc, curl_rc, want_rc, want_marker in cases:
            with self.subTest(label):
                rc, marker = run_probe(argv, msmtp_rc=msmtp_rc, curl_rc=curl_rc)
                self.assertEqual(want_rc, rc)
                if want_marker is not None:
                    self.assertEqual(want_marker, marker)

    def test_msmtp_curl_drops_the_mail_branch_when_email_is_disabled(self):
        """An SMTP outage must not flap the container into unhealthy."""
        self.assertEqual(
            ["CMD-SHELL", "curl -f --noproxy '*' http://127.0.0.1:80/ || exit 1"],
            probe("msmtp_curl", port=80, email_enabled=False),
        )


class TestBuild(unittest.TestCase):
    def test_each_flavor_brings_its_own_timings(self):
        self.assertEqual("10s", block("curl", port=80)["timeout"])
        self.assertEqual("3s", block("nc", port=80)["timeout"])
        self.assertEqual("120s", block("msmtp_curl", port=80)["start_period"])

    def test_the_service_entry_overrides_any_timing(self):
        got = block("curl", {"start_period": "20m", "retries": 9}, port=80)
        self.assertEqual(
            ("20m", 9, "1m"), (got["start_period"], got["retries"], got["interval"])
        )

    def test_an_empty_flavor_takes_the_explicit_test_argv(self):
        self.assertEqual(["CMD", "true"], block("", test=["CMD", "true"])["test"])

    def test_output_starts_at_column_zero_so_callers_indent_it(self):
        self.assertTrue(build("curl", {}, port=80).startswith("healthcheck:"))

    def test_output_carries_no_trailing_newline(self):
        self.assertFalse(build("curl", {}, port=80).endswith("\n"))

    def test_every_flavor_names_itself_in_the_registry(self):
        self.assertEqual(
            {"curl", "wget", "http", "http_status", "nc", "tcp", "connect"},
            set(PROBES),
        )
        self.assertTrue(all(key == cls.flavor for key, cls in PROBES.items()))

    def test_connect_opens_the_port_and_asserts_nothing_else(self):
        self.assertEqual(
            ["CMD", "bash", "-c", "</dev/tcp/127.0.0.1/9000"],
            probe("connect", port=9000),
        )

    def test_connect_composed_keeps_the_same_liveness_command(self):
        composed = probe(["msmtp", "connect"], port=9000, email_enabled=False)
        self.assertEqual(
            ["CMD-SHELL", "bash -c '</dev/tcp/127.0.0.1/9000' || exit 1"], composed
        )

    def test_an_unknown_name_raises_rather_than_rendering_nothing(self):
        with self.assertRaises(KeyError):
            compose("nosuchflavor", port=80)

    def test_a_prefix_is_not_a_probe_and_cannot_stand_alone(self):
        self.assertEqual({"msmtp"}, set(PREFIXES))
        self.assertNotIn("msmtp", PROBES)
        with self.assertRaises(ValueError):
            compose(["msmtp"], port=80)

    def test_two_probes_in_one_declaration_are_refused(self):
        with self.assertRaises(ValueError):
            compose(["curl", "connect"], port=80)

    def test_the_legacy_name_expands_to_the_composed_pair(self):
        self.assertEqual(["msmtp", "curl"], resolve_flavors("msmtp_curl"))
        self.assertEqual(
            probe(["msmtp", "curl"], port=80, email_enabled=False),
            probe("msmtp_curl", port=80, email_enabled=False),
        )

    def test_a_prefix_raises_a_timing_but_never_lowers_one(self):
        composed = block(["msmtp", "connect"], port=9000)
        self.assertEqual("15m", composed["start_period"])
        self.assertEqual("15m", block("connect", port=9000)["start_period"])
        self.assertEqual("120s", block(["msmtp", "curl"], port=80)["start_period"])
        self.assertEqual("30s", block("curl", port=80)["start_period"])

    def test_composing_takes_the_probes_interval(self):
        self.assertEqual("1m", block(["msmtp", "curl"], port=80)["interval"])

    def test_http_status_inherits_the_request_builder_from_tcp(self):
        self.assertTrue(issubclass(HttpStatus, Tcp))
        self.assertNotIn("[23][0-9][0-9]", probe("tcp", port=80))

    def test_probes_share_one_url_builder(self):
        self.assertEqual(
            Curl(port=9, path="x").url,
            Nc(port=9, path="x").url,
            Connect(port=9, path="x").url,
        )


if __name__ == "__main__":
    unittest.main()
