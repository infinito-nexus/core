from __future__ import annotations

import unittest

from cli.deploy.runner.command import (
    DEFAULT_OUTPUT,
    DEFAULT_RUNNER_COUNT,
    RUNNER_ROLE,
    _normalize_roles,
    _prepend_runner_role,
    build_parser,
)


class TestRunnerBuildParser(unittest.TestCase):
    def test_required_args_present(self):
        parser = build_parser()
        opts = {a.dest for a in parser._actions}  # noqa: SLF001
        self.assertIn("hostname", opts)
        self.assertIn("roles", opts)
        self.assertIn("distribution", opts)
        self.assertIn("port", opts)
        self.assertIn("output", opts)
        self.assertIn("runner_count", opts)

    def test_output_default_value(self):
        args = build_parser().parse_args(
            ["myhost", "--roles", "svc-runner", "--distribution", "debian"]
        )
        self.assertEqual(args.output, DEFAULT_OUTPUT)
        self.assertEqual(DEFAULT_OUTPUT, "/tmp/infinito-runner-deploy.log")

    def test_port_defaults_to_none(self):
        args = build_parser().parse_args(
            ["myhost", "--roles", "svc-runner", "--distribution", "debian"]
        )
        self.assertIsNone(args.port)

    def test_port_accepted(self):
        args = build_parser().parse_args(
            [
                "myhost",
                "--port",
                "2222",
                "--roles",
                "svc-runner",
                "--distribution",
                "debian",
            ]
        )
        self.assertEqual(args.port, 2222)

    def test_hostname_positional(self):
        args = build_parser().parse_args(
            [
                "runner.example.com",
                "--roles",
                "svc-runner",
                "--distribution",
                "archlinux",
            ]
        )
        self.assertEqual(args.hostname, "runner.example.com")

    def test_roles_required(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["myhost", "--distribution", "debian"])

    def test_distribution_required(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["myhost", "--roles", "svc-runner"])

    def test_hostname_required(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["--roles", "svc-runner", "--distribution", "debian"]
            )

    def test_custom_output_accepted(self):
        args = build_parser().parse_args(
            [
                "myhost",
                "--roles",
                "svc-runner",
                "--distribution",
                "debian",
                "--output",
                "/tmp/my-runner.log",
            ]
        )
        self.assertEqual(args.output, "/tmp/my-runner.log")

    def test_multiple_roles_accepted(self):
        args = build_parser().parse_args(
            ["myhost", "--roles", "svc-runner", "keycloak", "--distribution", "debian"]
        )
        self.assertEqual(args.roles, ["svc-runner", "keycloak"])

    def test_runner_count_default(self):
        args = build_parser().parse_args(
            ["myhost", "--roles", "svc-runner", "--distribution", "debian"]
        )
        self.assertEqual(args.runner_count, DEFAULT_RUNNER_COUNT)
        self.assertEqual(DEFAULT_RUNNER_COUNT, 15)

    def test_runner_count_accepted(self):
        args = build_parser().parse_args(
            [
                "myhost",
                "--roles",
                "svc-runner",
                "--distribution",
                "debian",
                "--runner-count",
                "5",
            ]
        )
        self.assertEqual(args.runner_count, 5)


class TestNormalizeRoles(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_normalize_roles([]), [])

    def test_single(self):
        self.assertEqual(_normalize_roles(["svc-runner"]), ["svc-runner"])

    def test_comma_separated(self):
        self.assertEqual(
            _normalize_roles(["svc-runner,keycloak,postgres"]),
            ["svc-runner", "keycloak", "postgres"],
        )

    def test_space_separated(self):
        self.assertEqual(
            _normalize_roles(["svc-runner", "keycloak", "postgres"]),
            ["svc-runner", "keycloak", "postgres"],
        )

    def test_mixed_space_and_comma(self):
        self.assertEqual(
            _normalize_roles(["svc-runner,keycloak", "postgres"]),
            ["svc-runner", "keycloak", "postgres"],
        )

    def test_deduplication_preserves_order(self):
        self.assertEqual(
            _normalize_roles(["keycloak", "keycloak", "postgres"]),
            ["keycloak", "postgres"],
        )

    def test_trimming_whitespace(self):
        self.assertEqual(
            _normalize_roles([" keycloak , postgres "]),
            ["keycloak", "postgres"],
        )

    def test_empty_entries_skipped(self):
        self.assertEqual(
            _normalize_roles(["keycloak,,postgres", ",svc-runner,"]),
            ["keycloak", "postgres", "svc-runner"],
        )


class TestPrependRunnerRole(unittest.TestCase):
    def test_prepends_when_absent(self):
        self.assertEqual(
            _prepend_runner_role(["keycloak", "postgres"]),
            [RUNNER_ROLE, "keycloak", "postgres"],
        )

    def test_no_duplicate_when_already_first(self):
        self.assertEqual(
            _prepend_runner_role([RUNNER_ROLE, "keycloak"]),
            [RUNNER_ROLE, "keycloak"],
        )

    def test_moves_to_front_when_not_first(self):
        self.assertEqual(
            _prepend_runner_role(["keycloak", RUNNER_ROLE, "postgres"]),
            [RUNNER_ROLE, "keycloak", "postgres"],
        )

    def test_empty_list_gets_runner_role(self):
        self.assertEqual(
            _prepend_runner_role([]),
            [RUNNER_ROLE],
        )

    def test_runner_role_constant_value(self):
        self.assertEqual(RUNNER_ROLE, "svc-runner")


if __name__ == "__main__":
    unittest.main()
