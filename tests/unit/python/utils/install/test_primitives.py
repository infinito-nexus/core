"""Unit tests for :mod:`utils.install.primitives`."""

from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock as mock
from http.client import RemoteDisconnected
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError

if TYPE_CHECKING:
    from typing import Self

from utils.install import primitives


class TestRunPrivileged(unittest.TestCase):
    def test_runs_directly_as_root(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=0),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["apt-get", "update"])
        run.assert_called_once_with(["apt-get", "update"], check=True)

    def test_prepends_sudo_for_non_root(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=1000),
            mock.patch.object(primitives.shutil, "which", return_value="/usr/bin/sudo"),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["apt-get", "update"])
        run.assert_called_once_with(["sudo", "apt-get", "update"], check=True)

    def test_no_sudo_when_unavailable(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=1000),
            mock.patch.object(primitives.shutil, "which", return_value=None),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["echo", "hi"])
        run.assert_called_once_with(["echo", "hi"], check=True)


class TestEnsureDirOnPath(unittest.TestCase):
    def test_prepends_when_absent(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=False):
            primitives.ensure_dir_on_path("/opt/bin")
            self.assertTrue(os.environ["PATH"].startswith("/opt/bin" + os.pathsep))

    def test_idempotent_when_present(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/opt/bin:/usr/bin"}, clear=False):
            primitives.ensure_dir_on_path("/opt/bin")
            self.assertEqual(os.environ["PATH"], "/opt/bin:/usr/bin")

    def test_empty_directory_noop(self) -> None:
        original = "/usr/bin"
        with mock.patch.dict(os.environ, {"PATH": original}, clear=False):
            primitives.ensure_dir_on_path("")
            self.assertEqual(os.environ["PATH"], original)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class TestDownloadFile(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.target = str(Path(self._tmp.name) / "asset")
        self.addCleanup(self._tmp.cleanup)

    def test_retries_a_dropped_connection_then_succeeds(self) -> None:
        opener = mock.Mock(
            side_effect=[RemoteDisconnected(), _FakeResponse(b"payload")]
        )
        with (
            mock.patch.object(primitives, "urlopen", opener),
            mock.patch.object(primitives.time, "sleep"),
        ):
            primitives.download_file("https://example.test/a", self.target)
        self.assertEqual(opener.call_count, 2)
        written = Path(self.target).read_bytes()  # nocheck: cache-read
        self.assertEqual(written, b"payload")

    def test_client_error_is_fatal_on_the_first_attempt(self) -> None:
        opener = mock.Mock(
            side_effect=HTTPError("https://example.test/a", 404, "Not Found", {}, None)
        )
        with (
            mock.patch.object(primitives, "urlopen", opener),
            mock.patch.object(primitives.time, "sleep"),
            self.assertRaises(HTTPError),
        ):
            primitives.download_file("https://example.test/a", self.target)
        self.assertEqual(opener.call_count, 1)
        self.assertFalse(Path(self.target).exists())

    def test_retryable_status_is_retried(self) -> None:
        opener = mock.Mock(
            side_effect=[
                HTTPError("https://example.test/a", 503, "Busy", {}, None),
                _FakeResponse(b"ok"),
            ]
        )
        with (
            mock.patch.object(primitives, "urlopen", opener),
            mock.patch.object(primitives.time, "sleep"),
        ):
            primitives.download_file("https://example.test/a", self.target)
        self.assertEqual(opener.call_count, 2)

    def test_exhausted_attempts_reraise(self) -> None:
        opener = mock.Mock(side_effect=RemoteDisconnected())
        with (
            mock.patch.object(primitives, "urlopen", opener),
            mock.patch.object(primitives.time, "sleep"),
            self.assertRaises(RemoteDisconnected),
        ):
            primitives.download_file("https://example.test/a", self.target)
        self.assertEqual(opener.call_count, primitives._DOWNLOAD_ATTEMPTS)


class TestInstallWithOptionalSudo(unittest.TestCase):
    def test_succeeds_without_sudo(self) -> None:
        with mock.patch.object(primitives.subprocess, "run") as run:
            primitives.install_with_optional_sudo(["install", "-d", "/tmp/x"])
        run.assert_called_once_with(["install", "-d", "/tmp/x"], check=True)

    def test_retries_with_sudo_on_failure(self) -> None:
        err = primitives.subprocess.CalledProcessError(returncode=1, cmd=["install"])
        with (
            mock.patch.object(
                primitives.subprocess, "run", side_effect=err
            ) as plain_run,
            mock.patch.object(primitives, "run_privileged") as privileged,
        ):
            primitives.install_with_optional_sudo(["install", "-d", "/usr/local/bin"])
        plain_run.assert_called_once()
        privileged.assert_called_once_with(["install", "-d", "/usr/local/bin"])


if __name__ == "__main__":
    unittest.main()
