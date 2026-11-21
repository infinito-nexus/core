"""Unit tests for ``utils.roles.header_trust``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.header_trust import (
    declaration_problems,
    header_trust_declarations,
    header_trust_exemptions,
    header_trust_headers,
    header_trust_roles,
    named_headers,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

RELAY = "proxy_set_header Remote-User $http_x_forwarded_user;\n"
SSO_BLOCK = "sso:\n  enabled: true\n  shared: true\n"


def _role(roles_dir: Path, name: str, content: str) -> None:
    templates = roles_dir / name / "templates"
    templates.mkdir(parents=True)
    (templates / "proxy.conf.j2").write_text(content, encoding="utf-8")


def _meta(roles_dir: Path, name: str, filename: str, content: str) -> None:
    meta = roles_dir / name / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / filename).write_text(content, encoding="utf-8")


def _declare(
    roles_dir: Path,
    name: str,
    proxy_secret: str,
    switch: str,
    files: str = "[templates/proxy.conf.j2]",
) -> None:
    _meta(
        roles_dir,
        name,
        "services.yml",
        SSO_BLOCK
        + f"  header_trust:\n    proxy_secret: {proxy_secret}\n    switch: {switch}\n"
        + f"    files: {files}\n",
    )


def _file(roles_dir: Path, name: str, rel: str, content: str) -> None:
    path = roles_dir / name / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestHeaderTrustRoles(unittest.TestCase):
    def test_a_role_naming_a_trusted_header_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)

            self.assertEqual(
                header_trust_roles(roles_dir),
                {"web-app-trusting": ["templates/proxy.conf.j2"]},
            )

    def test_a_head_nocheck_marker_exempts_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)
            _role(
                roles_dir,
                "web-app-exempt",
                "# nocheck: header-trust  reads no identity header\n" + RELAY,
            )

            self.assertEqual(
                sorted(header_trust_roles(roles_dir)), ["web-app-trusting"]
            )

    def test_a_blanking_line_is_no_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-stripping", 'proxy_set_header Remote-User "";\n')

            self.assertEqual(header_trust_roles(roles_dir), {})

    def test_a_caller_mutating_the_result_leaves_the_next_call_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)
            header_trust_roles(roles_dir)["web-app-trusting"].append("forged")
            header_trust_headers(roles_dir).clear()

            self.assertEqual(
                header_trust_roles(roles_dir),
                {"web-app-trusting": ["templates/proxy.conf.j2"]},
            )
            self.assertEqual(
                header_trust_headers(roles_dir),
                {"web-app-trusting": ["Remote-User", "X-Forwarded-User"]},
            )


class TestNamedHeaders(unittest.TestCase):
    def test_every_spelling_maps_to_the_canonical_header(self):
        text = (
            "proxy_set_header Remote-User $http_x_forwarded_user;\n"
            "user = META['HTTP_X_REMOTE_USER']\n"
        )
        self.assertEqual(
            ["Remote-User", "X-Forwarded-User", "X-Remote-User"], named_headers(text)
        )

    def test_the_bare_underscore_spelling_of_an_x_header_is_named(self):
        """FusionDirectory names its header as a $_SERVER key suffix."""
        self.assertEqual(
            ["X-Forwarded-Preferred-Username"],
            named_headers('NAME: "X_FORWARDED_PREFERRED_USERNAME"\n'),
        )
        self.assertEqual(
            ["X-Auth-Request-Email"], named_headers("x_auth_request_email\n")
        )

    def test_the_bare_underscore_spelling_skips_nginx_remote_user(self):
        """nginx's own $remote_user is the basic-auth user, not a header."""
        self.assertEqual([], named_headers("log_format main '$remote_user';\n"))
        self.assertEqual([], named_headers("set $u remote_email;\n"))

    def test_a_longer_identifier_is_no_bare_spelling(self):
        self.assertEqual([], named_headers("my_x_forwarded_user_count = 1\n"))

    def test_the_access_token_header_is_detected(self):
        self.assertEqual(
            ["X-Forwarded-Access-Token"],
            named_headers("token = req.headers['x-forwarded-access-token']\n"),
        )

    def test_a_blanking_line_names_no_header(self):
        self.assertEqual([], named_headers('proxy_set_header Remote-User "";\n'))

    def test_the_headers_of_a_role_are_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)

            self.assertEqual(
                {"web-app-trusting": ["Remote-User", "X-Forwarded-User"]},
                header_trust_headers(roles_dir),
            )


class TestExemptions(unittest.TestCase):
    def test_the_marker_reason_is_the_stated_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(
                roles_dir,
                "web-app-exempt",
                "# nocheck: header-trust  reads no identity header\n" + RELAY,
            )

            self.assertEqual(
                {
                    "web-app-exempt": [
                        ("templates/proxy.conf.j2", "reads no identity header")
                    ]
                },
                header_trust_exemptions(roles_dir),
            )
            self.assertEqual({}, header_trust_headers(roles_dir))

    def test_a_trusting_file_is_no_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)

            self.assertEqual({}, header_trust_exemptions(roles_dir))


class TestDeclarationProblems(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.roles_dir = Path(self._tmp.name)

    def test_a_valid_declaration_passes(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _declare(self.roles_dir, "web-app-trusting", "false", "services.sso.enabled")

        self.assertEqual([], declaration_problems(self.roles_dir))
        self.assertEqual(
            {
                "web-app-trusting": {
                    "proxy_secret": False,
                    "switch": "services.sso.enabled",
                    "files": ["templates/proxy.conf.j2"],
                }
            },
            header_trust_declarations(self.roles_dir),
        )

    def test_a_declared_file_that_names_no_header_fails(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _file(self.roles_dir, "web-app-trusting", "files/app.py", "print('hi')\n")
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "false",
            "services.sso.enabled",
            "[files/app.py]",
        )

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems))
        self.assertIn("files/app.py, which names no trusted header", problems[0])

    def test_a_declared_file_may_name_the_header_through_a_role_variable(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _file(
            self.roles_dir,
            "web-app-trusting",
            ROLE_FILE_VARS_MAIN,
            'APP_HEADER: "X-Remote-User"\n',
        )
        _file(
            self.roles_dir,
            "web-app-trusting",
            "templates/env.j2",
            "HEADER={{ APP_HEADER }}\n",
        )
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "false",
            "services.sso.enabled",
            "[templates/env.j2]",
        )

        self.assertEqual([], declaration_problems(self.roles_dir))

    def test_a_declared_file_that_does_not_exist_fails(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "false",
            "services.sso.enabled",
            "[gone.py]",
        )

        self.assertIn(
            "gone.py, which does not exist", declaration_problems(self.roles_dir)[0]
        )

    def test_a_declared_file_that_cannot_trust_a_header_fails(self):
        """Documentation, tests, Playwright and other roles name headers without trusting them."""
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _role(
            self.roles_dir,
            "web-app-other",
            "# nocheck: header-trust  only a fixture\n" + RELAY,
        )
        for rel in (
            "README.md",
            "templates/test.env.j2",
            "files/test/test.sh",
            "files/playwright/spec.js",
        ):
            _file(self.roles_dir, "web-app-trusting", rel, RELAY)
        _file(
            self.roles_dir,
            "web-app-trusting",
            "files/exempt.conf",
            "# nocheck: header-trust  a fixture\n" + RELAY,
        )
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "false",
            "services.sso.enabled",
            "[README.md, templates/test.env.j2, files/test/test.sh, files/playwright/spec.js, "
            "../web-app-other/templates/proxy.conf.j2, files/exempt.conf]",
        )

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(6, len(problems), problems)
        self.assertIn("README.md, which is documentation", problems[0])
        self.assertIn("templates/test.env.j2, which is a test file", problems[1])
        self.assertIn("files/test/test.sh, which is a test file", problems[2])
        self.assertIn("files/playwright/spec.js, which is a test file", problems[3])
        self.assertIn("proxy.conf.j2, which lies outside the role", problems[4])
        self.assertIn(
            "files/exempt.conf, which carries # nocheck: header-trust", problems[5]
        )

    def test_a_header_named_only_in_a_comment_is_no_trust(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _file(
            self.roles_dir,
            "web-app-trusting",
            ROLE_FILE_VARS_MAIN,
            'APP_HEADER: "X_FORWARDED_PREFERRED_USERNAME"\n',
        )
        _file(
            self.roles_dir,
            "web-app-trusting",
            "files/boot.sh",
            "#   APP_HEADER  the header\necho ok\n",
        )
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "false",
            "services.sso.enabled",
            "[files/boot.sh]",
        )

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("outside its comments", problems[0])

    def test_a_marker_without_a_reason_fails(self):
        _role(self.roles_dir, "web-app-exempt", "# nocheck: header-trust\n" + RELAY)

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems))
        self.assertIn("without a reason", problems[0])

    def test_a_marker_with_a_reason_passes(self):
        _role(
            self.roles_dir,
            "web-app-exempt",
            "# nocheck: header-trust  reads no identity header\n" + RELAY,
        )

        self.assertEqual([], declaration_problems(self.roles_dir))

    def test_a_detected_role_without_a_declaration_fails(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems))
        self.assertIn("declares no sso.header_trust", problems[0])

    def test_a_declaration_on_an_undetected_role_is_dead(self):
        _declare(self.roles_dir, "web-app-plain", "false", "services.sso.enabled")

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems))
        self.assertIn("declaration is dead", problems[0])

    def test_a_proxy_secret_must_be_a_declared_credential(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _declare(
            self.roles_dir,
            "web-app-trusting",
            "sso_proxy_secret",
            "services.sso.enabled",
        )

        self.assertIn("proxy_secret", declaration_problems(self.roles_dir)[0])

        _meta(
            self.roles_dir,
            "web-app-trusting",
            "secrets.yml",
            "credentials:\n  sso_proxy_secret:\n    description: x\n",
        )
        self.assertEqual([], declaration_problems(self.roles_dir))

    def test_a_switch_naming_a_missing_service_path_fails(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _declare(self.roles_dir, "web-app-trusting", "false", "services.ldap.enabled")

        problems = declaration_problems(self.roles_dir)
        self.assertEqual(1, len(problems))
        self.assertIn("services.ldap.enabled", problems[0])

    def test_a_declaration_with_a_missing_field_fails(self):
        _role(self.roles_dir, "web-app-trusting", RELAY)
        _meta(
            self.roles_dir,
            "web-app-trusting",
            "services.yml",
            SSO_BLOCK + "  header_trust:\n    switch: services.sso.enabled\n",
        )

        self.assertIn("must hold exactly", declaration_problems(self.roles_dir)[0])


if __name__ == "__main__":
    unittest.main()
