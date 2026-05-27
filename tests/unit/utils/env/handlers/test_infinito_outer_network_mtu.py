"""Unit tests for :mod:`utils.env.handlers.infinito_outer_network_mtu`."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers import infinito_outer_network_mtu as handler


def _ctx(static: dict[str, str] | None = None) -> BuildContext:
    return BuildContext(
        static=dict(static or {}),
        static_comments={handler.KEY: "MTU comment"},
        repo_root=Path("/repo"),
        on_gha=False,
        on_act=False,
    )


class TestDefaultRouteIface(unittest.TestCase):
    def test_returns_iface_from_proc_net_route(self) -> None:
        proc = (
            "Iface\tDestination\tGateway\t...\n"
            "eth0\t00000000\tABCD1234\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        )
        with (
            patch.object(handler.Path, "is_file", return_value=True),
            patch.object(handler.Path, "read_text", return_value=proc),
        ):
            self.assertEqual(handler._default_route_iface(), "eth0")

    def test_returns_none_when_no_default_route(self) -> None:
        proc = (
            "Iface\tDestination\tGateway\t...\n"
            "eth0\t0100A8C0\t00000000\t0001\t0\t0\t0\tFFFFFF00\t0\t0\t0\n"
        )
        with (
            patch.object(handler.Path, "is_file", return_value=True),
            patch.object(handler.Path, "read_text", return_value=proc),
        ):
            self.assertIsNone(handler._default_route_iface())

    def test_returns_none_when_proc_file_missing(self) -> None:
        with patch.object(handler.Path, "is_file", return_value=False):
            self.assertIsNone(handler._default_route_iface())

    def test_returns_none_on_read_error(self) -> None:
        with (
            patch.object(handler.Path, "is_file", return_value=True),
            patch.object(handler.Path, "read_text", side_effect=OSError("denied")),
        ):
            self.assertIsNone(handler._default_route_iface())


class TestIfaceMtu(unittest.TestCase):
    def test_returns_stripped_value(self) -> None:
        with patch.object(handler.Path, "read_text", return_value="1400\n"):
            self.assertEqual(handler._iface_mtu("eth0"), "1400")

    def test_returns_none_on_read_error(self) -> None:
        with patch.object(handler.Path, "read_text", side_effect=OSError("nope")):
            self.assertIsNone(handler._iface_mtu("eth0"))


class TestDetectOuterMtu(unittest.TestCase):
    def test_returns_mtu_when_iface_and_file_present(self) -> None:
        with (
            patch.object(handler, "_default_route_iface", return_value="eth0"),
            patch.object(handler, "_iface_mtu", return_value="1450"),
        ):
            self.assertEqual(handler.detect_outer_mtu(), "1450")

    def test_returns_none_when_no_default_iface(self) -> None:
        with patch.object(handler, "_default_route_iface", return_value=None):
            self.assertIsNone(handler.detect_outer_mtu())

    def test_returns_none_when_mtu_unreadable(self) -> None:
        with (
            patch.object(handler, "_default_route_iface", return_value="eth0"),
            patch.object(handler, "_iface_mtu", return_value=None),
        ):
            self.assertIsNone(handler.detect_outer_mtu())


class TestApply(unittest.TestCase):
    def test_writes_detected_mtu(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(handler, "detect_outer_mtu", return_value="1400"),
        ):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(static={handler.KEY: "1500"}))
        self.assertEqual(eb.values[handler.KEY], "1400")
        self.assertEqual(eb.comments[handler.KEY], "MTU comment")

    def test_falls_back_to_static_when_detection_fails(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(handler, "detect_outer_mtu", return_value=None),
        ):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(static={handler.KEY: "1500"}))
        self.assertEqual(eb.values[handler.KEY], "1500")

    def test_skips_when_detection_and_fallback_both_empty(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(handler, "detect_outer_mtu", return_value=None),
        ):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(static={}))
        self.assertNotIn(handler.KEY, eb.values)

    def test_caller_env_wins_over_detection(self) -> None:
        with (
            patch.dict("os.environ", {handler.KEY: "9000"}, clear=True),
            patch.object(handler, "detect_outer_mtu", return_value="1400"),
        ):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(static={handler.KEY: "1500"}))
        self.assertEqual(eb.values[handler.KEY], "9000")


if __name__ == "__main__":
    unittest.main()
