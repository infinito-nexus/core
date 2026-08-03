import unittest

from utils.cache.yaml import load_yaml_str
from utils.docker.healthcheck import PROBES, Curl, HttpStatus, MsmtpCurl, Nc, Tcp, build


def probe(flavor, **context):
    return PROBES[flavor](**context).test()


def block(flavor, overrides=None, **context):
    return load_yaml_str(build(flavor, overrides or {}, **context))["healthcheck"]


class TestCurl(unittest.TestCase):
    def test_single_sample_uses_the_exec_form(self):
        self.assertEqual(
            ["CMD", "curl", "-f", "http://127.0.0.1:80/"],
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
            ["CMD", "curl", "-f", "-H", "Host: app.example", "http://127.0.0.1:80/"],
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
                    "|| curl -fsS http://127.0.0.1:8080/ >/dev/null"
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
        self.assertIn("msmtp -t void@example", argv[1])
        self.assertTrue(argv[1].endswith("curl -f http://127.0.0.1:80/ || exit 1"))

    def test_msmtp_curl_drops_the_mail_branch_when_email_is_disabled(self):
        """An SMTP outage must not flap the container into unhealthy."""
        self.assertEqual(
            ["CMD-SHELL", "curl -f http://127.0.0.1:80/ || exit 1"],
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
            {"curl", "wget", "http", "http_status", "nc", "tcp", "msmtp_curl"},
            set(PROBES),
        )
        self.assertTrue(all(key == cls.flavor for key, cls in PROBES.items()))

    def test_http_status_inherits_the_request_builder_from_tcp(self):
        self.assertTrue(issubclass(HttpStatus, Tcp))
        self.assertNotIn("[23][0-9][0-9]", probe("tcp", port=80))

    def test_probes_share_one_url_builder(self):
        self.assertEqual(
            Curl(port=9, path="x").url,
            Nc(port=9, path="x").url,
            MsmtpCurl(port=9, path="x").url,
        )


if __name__ == "__main__":
    unittest.main()
