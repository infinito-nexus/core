"""The front proxy's access log keeps no tokens from URLs."""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATE = "roles/sys-svc-webserver-core/templates/nginx.conf.j2"

LEAKING_VARIABLE = re.compile(
    r"\$\{?(request|request_uri|args|query_string|is_args|arg_\w+|http_referer|remote_user)\b"
)

REDACTED_PATH = "$infinito_access_log_path"

MODES = {"debug": True, "production": False}


def render(debug: bool) -> str:
    """Return the rendered nginx.conf.

    Args:
        debug: the value of ``MODE_DEBUG``.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    return env.get_template(TEMPLATE).render(
        MODE_DEBUG=debug,
        DEPLOYMENT_MODE="compose",
        WEBSERVER_PROXY_WORKER_PROCESSES=1,
        WEBSERVER_PROXY_WORKER_CONNECTIONS=256,
        WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE=512,
        lookup=lambda _kind, key: (
            ["/etc/nginx/conf.d/http/"]
            if key.endswith("http_includes")
            else f"/var/lib/nginx/{key}"
        ),
    )


def directives(rendered: str, name: str) -> list[str]:
    """Return the arguments of every ``name`` directive, joined across lines.

    Args:
        rendered: the rendered nginx.conf.
        name: the directive, e.g. ``log_format``.
    """
    return re.findall(rf"^\s*{name}\s+([^;]*);", rendered, re.MULTILINE)


def log_formats(rendered: str) -> dict[str, str]:
    """Return every declared log format body by its name.

    Args:
        rendered: the rendered nginx.conf.
    """
    return {
        body.split(maxsplit=1)[0]: body.split(maxsplit=1)[1]
        for body in directives(rendered, "log_format")
    }


def logged_path(rendered: str, request_uri: str) -> str:
    """Return the path the access log writes, resolved as nginx's map does.

    Args:
        rendered: the rendered nginx.conf.
        request_uri: the request URI as the client sent it.
    """
    block = re.search(
        r"map \$request_uri \$infinito_access_log_path \{(.*?)\n\s*\}",
        rendered,
        re.DOTALL,
    )
    if block is None:
        raise AssertionError("nginx.conf declares no map for $infinito_access_log_path")
    for source, value in re.findall(
        r'^\s*"([^"]+)"\s+"([^"]*)";', block.group(1), re.MULTILINE
    ):
        caseless = source.startswith("~*")
        match = re.search(
            source[2:] if caseless else source[1:],
            request_uri,
            re.IGNORECASE if caseless else 0,
        )
        if match:
            return re.sub(
                r"\$\{(\w+)\}|\$(\w+)",
                lambda var, m=match: m.group(var.group(1) or var.group(2)),
                value,
            )
    return ""


class TestAccessLogFormat(unittest.TestCase):
    def test_every_mode_writes_its_access_log_in_a_format_declared_here(self):
        for mode, debug in MODES.items():
            with self.subTest(mode=mode):
                rendered = render(debug)
                logs = [args.split() for args in directives(rendered, "access_log")]
                self.assertTrue(logs)
                for log in logs:
                    self.assertEqual(len(log), 2, log)
                    self.assertIn(log[1], log_formats(rendered))

    def test_no_format_logs_the_query_string_the_referer_or_the_raw_request(self):
        for mode, debug in MODES.items():
            for name, body in log_formats(render(debug)).items():
                with self.subTest(mode=mode, format=name):
                    self.assertIsNone(LEAKING_VARIABLE.search(body), body)

    def test_every_format_logs_method_redacted_path_and_status(self):
        for mode, debug in MODES.items():
            for name, body in log_formats(render(debug)).items():
                with self.subTest(mode=mode, format=name):
                    self.assertIn(
                        f'"$request_method {REDACTED_PATH} $server_protocol"', body
                    )
                    self.assertIn("$status", body)

    def test_the_debug_format_keeps_host_timings_and_upstream(self):
        body = log_formats(render(True))["debug"]
        for variable in ("$host", "$request_time", "$upstream_response_time"):
            with self.subTest(variable=variable):
                self.assertIn(variable, body)


class TestLoggedPath(unittest.TestCase):
    rendered: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.rendered = render(False)

    def test_the_query_string_is_dropped(self):
        for request_uri, expected in (
            ("/", "/"),
            ("/index.php?access_token=s3cr3t", "/index.php"),
            ("/api/v1/items?page=2&token=s3cr3t", "/api/v1/items"),
            (
                "/realms/x/login-actions/action-token?key=s3cr3t",
                "/realms/x/login-actions/action-token",
            ),
        ):
            with self.subTest(request_uri=request_uri):
                self.assertEqual(logged_path(self.rendered, request_uri), expected)

    def test_token_routes_are_redacted(self):
        for request_uri, expected in (
            ("/password/reset/s3cr3t?email=a%40b.c", "/password/reset/[redacted]"),
            ("/i/confirm-email/s3cr3t/s3cr3t2", "/i/confirm-email/[redacted]"),
            ("/accounts/confirm-email/s3cr3t/", "/accounts/confirm-email/[redacted]"),
            (
                "/index.php/lostpassword/reset/form/s3cr3t/alice",
                "/index.php/lostpassword/reset/form/[redacted]",
            ),
            ("/u/password-reset/s3cr3t", "/u/password-reset/[redacted]"),
            ("/reset-password/s3cr3t", "/reset-password/[redacted]"),
            ("/session/email-login/s3cr3t", "/session/email-login/[redacted]"),
            ("/u/activate-account/s3cr3t", "/u/activate-account/[redacted]"),
            ("/Password/Reset/s3cr3t", "/Password/Reset/[redacted]"),
        ):
            with self.subTest(request_uri=request_uri):
                logged = logged_path(self.rendered, request_uri)
                self.assertEqual(logged, expected)
                self.assertNotIn("s3cr3t", logged)

    def test_lookalike_paths_are_logged_unchanged(self):
        for request_uri in (
            "/password/reset",
            "/xpassword/reset/abc",
            "/settings/password",
            "/confirm-email",
        ):
            with self.subTest(request_uri=request_uri):
                self.assertEqual(logged_path(self.rendered, request_uri), request_uri)

    def test_both_modes_share_the_same_map(self):
        self.assertEqual(
            logged_path(render(True), "/password/reset/s3cr3t?x=1"),
            logged_path(self.rendered, "/password/reset/s3cr3t?x=1"),
        )


if __name__ == "__main__":
    unittest.main()
