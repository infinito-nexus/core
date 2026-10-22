"""Unit tests for :mod:`utils.install.node`."""

from __future__ import annotations

import datetime as dt
import hashlib
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.install import node as node_mod

SCHEDULE = {
    "v20": {"end": "2026-04-30"},
    "v22": {"end": "2027-04-30"},
    "v24": {"end": "2028-04-30"},
}
TODAY = dt.date(2026, 10, 21)


class TestLineIsSupported(unittest.TestCase):
    def test_line_before_its_end_is_supported(self) -> None:
        self.assertTrue(node_mod.line_is_supported("v22", SCHEDULE, TODAY))

    def test_line_on_its_end_date_is_supported(self) -> None:
        self.assertTrue(
            node_mod.line_is_supported("v20", SCHEDULE, dt.date(2026, 4, 30))
        )

    def test_line_past_its_end_is_not_supported(self) -> None:
        self.assertFalse(node_mod.line_is_supported("v20", SCHEDULE, TODAY))

    def test_unknown_line_is_not_supported(self) -> None:
        self.assertFalse(node_mod.line_is_supported("v18", SCHEDULE, TODAY))


class TestNewestLts(unittest.TestCase):
    def test_skips_current_releases(self) -> None:
        index = [
            {"version": "v26.1.0", "lts": False},
            {"version": "v24.22.1", "lts": "Krypton"},
            {"version": "v22.30.0", "lts": "Jod"},
        ]
        self.assertEqual(node_mod.newest_lts(index), "v24.22.1")

    def test_raises_without_lts(self) -> None:
        with self.assertRaises(RuntimeError):
            node_mod.newest_lts([{"version": "v26.1.0", "lts": False}])


class TestTarballName(unittest.TestCase):
    def test_maps_x86_64(self) -> None:
        self.assertEqual(
            node_mod.tarball_name("v24.22.1", "Linux", "x86_64"),
            "node-v24.22.1-linux-x64.tar.gz",
        )

    def test_maps_aarch64(self) -> None:
        self.assertEqual(
            node_mod.tarball_name("v24.22.1", "Linux", "aarch64"),
            "node-v24.22.1-linux-arm64.tar.gz",
        )

    def test_raises_for_unknown_machine(self) -> None:
        with self.assertRaises(RuntimeError):
            node_mod.tarball_name("v24.22.1", "Linux", "riscv64")

    def test_refuses_a_host_that_is_not_linux(self) -> None:
        with self.assertRaises(RuntimeError):
            node_mod.tarball_name("v24.22.1", "Darwin", "x86_64")


class TestExpectedSha256(unittest.TestCase):
    def test_finds_the_listed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shasums = Path(tmp) / "SHASUMS256.txt"
            shasums.write_text(
                "aaa  node-v24.22.1-linux-arm64.tar.gz\n"
                "bbb  node-v24.22.1-linux-x64.tar.gz\n",
                encoding="utf-8",
            )
            self.assertEqual(
                node_mod.expected_sha256(shasums, "node-v24.22.1-linux-x64.tar.gz"),
                "bbb",
            )

    def test_raises_for_an_unlisted_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shasums = Path(tmp) / "SHASUMS256.txt"
            shasums.write_text("aaa  other.tar.gz\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                node_mod.expected_sha256(shasums, "node-v24.22.1-linux-x64.tar.gz")


class TestInstallUpstreamLts(unittest.TestCase):
    def test_refuses_a_tarball_whose_checksum_differs(self) -> None:
        name = "node-v24.22.1-linux-x64.tar.gz"

        def fake_download(url: str, output: str, **_kwargs: object) -> None:
            path = Path(output)
            if url.endswith("index.json"):
                path.write_text(
                    '[{"version": "v24.22.1", "lts": "Krypton"}]', encoding="utf-8"
                )
            elif url.endswith("SHASUMS256.txt"):
                listed = hashlib.sha256(b"published").hexdigest()
                path.write_text(f"{listed}  {name}\n", encoding="utf-8")
            else:
                path.write_bytes(b"tampered")

        with (
            mock.patch.object(node_mod, "download_file", side_effect=fake_download),
            mock.patch.object(node_mod, "_verify_signature"),
            mock.patch.object(node_mod.platform, "system", return_value="Linux"),
            mock.patch.object(node_mod.platform, "machine", return_value="x86_64"),
            mock.patch.object(node_mod, "run_privileged") as extract,
            self.assertRaises(RuntimeError),
        ):
            node_mod.install_upstream_lts()
        extract.assert_not_called()


class TestEnsureNodePresent(unittest.TestCase):
    def setUp(self) -> None:
        node_mod.ensure_node_present.cache_clear()
        self.addCleanup(node_mod.ensure_node_present.cache_clear)

    def _run(self, line: str) -> mock.MagicMock:
        def fake_download(_url: str, output: str, **_kwargs: object) -> None:
            Path(output).write_text(
                '{"v20": {"end": "2026-04-30"}, "v22": {"end": "2099-04-30"}}',
                encoding="utf-8",
            )

        with (
            mock.patch.object(node_mod, "ensure_command_present") as ensure,
            mock.patch.object(node_mod, "installed_line", return_value=line),
            mock.patch.object(node_mod, "download_file", side_effect=fake_download),
            mock.patch.object(node_mod, "install_upstream_lts") as upstream,
        ):
            node_mod.ensure_node_present()
        ensure.assert_called_once_with("node")
        return upstream

    def test_keeps_a_supported_distro_node(self) -> None:
        self._run("v22").assert_not_called()

    def test_replaces_an_end_of_life_distro_node(self) -> None:
        self._run("v20").assert_called_once_with()

    def test_propagates_the_hard_failure(self) -> None:
        with (
            mock.patch.object(
                node_mod, "ensure_command_present", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(RuntimeError),
        ):
            node_mod.ensure_node_present()


if __name__ == "__main__":
    unittest.main()
