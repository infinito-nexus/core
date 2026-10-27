from __future__ import annotations

import subprocess
import unittest
import unittest.mock as mock

from utils.install.lint import shfmt

_WANT = shfmt.resolve_release("shfmt")[1]


def _ensure(*versions: str | None) -> mock.MagicMock:
    with (
        mock.patch.object(shfmt, "_installed_version", side_effect=list(versions)),
        mock.patch.object(shfmt, "_install_binary") as install,
    ):
        shfmt.ensure()
    return install


class TestEnsure(unittest.TestCase):
    def test_the_pinned_release_stays(self) -> None:
        _ensure(_WANT).assert_not_called()

    def test_a_distribution_release_is_replaced(self) -> None:
        _ensure("3.8.0", _WANT).assert_called_once()

    def test_a_missing_shfmt_is_installed(self) -> None:
        _ensure(None, _WANT).assert_called_once()

    def test_a_shadowed_install_fails_loudly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must precede"):
            _ensure("3.8.0", "3.8.0")


class TestInstalledVersion(unittest.TestCase):
    def _version(self, **run: object) -> str | None:
        with mock.patch.object(shfmt.subprocess, "run", **run):
            return shfmt._installed_version()

    def test_a_release_binary_drops_its_v(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout="v3.14.1\n", stderr="")
        self.assertEqual(self._version(return_value=done), "3.14.1")

    def test_a_distribution_build_reads_as_is(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout="3.8.0\n", stderr="")
        self.assertEqual(self._version(return_value=done), "3.8.0")

    def test_a_missing_binary_reads_as_none(self) -> None:
        self.assertIsNone(self._version(side_effect=FileNotFoundError("shfmt")))


if __name__ == "__main__":
    unittest.main()
