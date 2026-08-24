from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from utils.nexus.list_apt_proxy_repos import main


def _run(payload) -> tuple[int, str]:
    """Feed *payload* (str or already-encoded JSON) to main()'s stdin and
    capture its stdout. Returns (exit_code, stdout)."""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    buf = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), redirect_stdout(buf):
        rc = main()
    return rc, buf.getvalue()


class TestListAptProxyRepos(unittest.TestCase):
    def test_returns_apt_proxy_names_in_input_order(self) -> None:
        rc, out = _run(
            [
                {"name": "apt-debian", "format": "apt", "type": "proxy"},
                {"name": "apt-ubuntu", "format": "apt", "type": "proxy"},
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["apt-debian", "apt-ubuntu"])

    def test_filters_non_apt_formats(self) -> None:
        rc, out = _run(
            [
                {"name": "apt-debian", "format": "apt", "type": "proxy"},
                {"name": "docker-hub", "format": "docker", "type": "proxy"},
                {"name": "raw-things", "format": "raw", "type": "proxy"},
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["apt-debian"])

    def test_filters_non_proxy_types(self) -> None:
        rc, out = _run(
            [
                {"name": "apt-debian", "format": "apt", "type": "proxy"},
                {"name": "apt-hosted", "format": "apt", "type": "hosted"},
                {"name": "apt-group", "format": "apt", "type": "group"},
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["apt-debian"])

    def test_no_match_exits_1(self) -> None:
        rc, out = _run(
            [
                {"name": "docker-hub", "format": "docker", "type": "proxy"},
            ]
        )
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_empty_list_exits_1(self) -> None:
        rc, out = _run([])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_invalid_json_exits_1(self) -> None:
        rc, out = _run("not-json-at-all{{{")
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_non_list_payload_exits_1(self) -> None:
        rc, out = _run({"format": "apt", "type": "proxy", "name": "x"})
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_skips_non_dict_entries(self) -> None:
        rc, out = _run(
            [
                "not-a-dict",
                None,
                42,
                {"name": "apt-debian", "format": "apt", "type": "proxy"},
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["apt-debian"])

    def test_skips_entries_without_string_name(self) -> None:
        rc, out = _run(
            [
                {"name": "", "format": "apt", "type": "proxy"},
                {"name": None, "format": "apt", "type": "proxy"},
                {"format": "apt", "type": "proxy"},
                {"name": 123, "format": "apt", "type": "proxy"},
                {"name": "apt-debian", "format": "apt", "type": "proxy"},
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["apt-debian"])

    def test_realistic_live_payload(self) -> None:
        rc, out = _run(
            [
                {
                    "name": "apt-debian",
                    "format": "apt",
                    "type": "proxy",
                    "url": "http://infinito-package-cache:8081/repository/apt-debian",
                },
                {
                    "name": "apt-ubuntu",
                    "format": "apt",
                    "type": "proxy",
                    "url": "http://infinito-package-cache:8081/repository/apt-ubuntu",
                },
                {
                    "name": "apt-debian-security",
                    "format": "apt",
                    "type": "proxy",
                },
                {
                    "name": "apt-ubuntu-security",
                    "format": "apt",
                    "type": "proxy",
                },
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(
            out.splitlines(),
            [
                "apt-debian",
                "apt-ubuntu",
                "apt-debian-security",
                "apt-ubuntu-security",
            ],
        )


if __name__ == "__main__":
    unittest.main()
