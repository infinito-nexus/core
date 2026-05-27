"""Unit tests for cli.contributing.network.diagnose.cli."""

from __future__ import annotations

import io
import socket
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cli.contributing.network.diagnose import cli as diag_cli


class TestResolveHosts(unittest.TestCase):
    def test_returns_defaults_when_env_unset(self) -> None:
        with patch.dict(diag_cli.os.environ, {}, clear=True):
            hosts = diag_cli.resolve_hosts()
        self.assertEqual(hosts, list(diag_cli.DEFAULT_HOSTS))

    def test_appends_env_hosts(self) -> None:
        with patch.dict(
            diag_cli.os.environ,
            {diag_cli.EXTRA_HOSTS_ENV: "a.example b.example"},
            clear=True,
        ):
            hosts = diag_cli.resolve_hosts()
        self.assertEqual(hosts[-2:], ["a.example", "b.example"])
        self.assertEqual(hosts[:-2], list(diag_cli.DEFAULT_HOSTS))


class TestMain(unittest.TestCase):
    def test_returns_zero_and_runs_v4_only_when_no_v6(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(diag_cli, "show_identity") as si,
            patch.object(diag_cli, "ensure_tools") as et,
            patch.object(diag_cli, "show_iface_routes"),
            patch.object(diag_cli, "show_resolv"),
            patch.object(diag_cli, "show_hosts"),
            patch.object(diag_cli, "show_proxies"),
            patch.object(diag_cli, "show_ca_bundle"),
            patch.object(diag_cli, "has_ipv6_default_route", return_value=False),
            patch.object(diag_cli, "per_host_check") as phc,
            redirect_stdout(buf),
        ):
            rc = diag_cli.main()

        self.assertEqual(rc, 0)
        si.assert_called_once()
        et.assert_called_once()
        phc.assert_called_once()
        args, _kwargs = phc.call_args
        self.assertEqual(args[1], socket.AF_INET)
        self.assertEqual(args[2], "IPv4")
        self.assertIn("[SKIP] no IPv6 default route", buf.getvalue())

    def test_runs_v6_when_route_present(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(diag_cli, "show_identity"),
            patch.object(diag_cli, "ensure_tools"),
            patch.object(diag_cli, "show_iface_routes"),
            patch.object(diag_cli, "show_resolv"),
            patch.object(diag_cli, "show_hosts"),
            patch.object(diag_cli, "show_proxies"),
            patch.object(diag_cli, "show_ca_bundle"),
            patch.object(diag_cli, "has_ipv6_default_route", return_value=True),
            patch.object(diag_cli.socket, "has_ipv6", True),
            patch.object(diag_cli, "per_host_check") as phc,
            redirect_stdout(buf),
        ):
            rc = diag_cli.main()

        self.assertEqual(rc, 0)
        self.assertEqual(phc.call_count, 2)
        families = [call.args[1] for call in phc.call_args_list]
        self.assertEqual(families, [socket.AF_INET, socket.AF_INET6])


if __name__ == "__main__":
    unittest.main()
