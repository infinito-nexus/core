import os
import subprocess
import unittest
import unittest.mock as mock
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.i18n.libretranslate import (
    LibreTranslate,
    accelerated,
    deploying,
    server,
)


class TestParallelDeployIsRefused(unittest.TestCase):
    def test_a_running_deploy_stops_the_translation(self) -> None:
        with (
            mock.patch("utils.i18n.libretranslate.deploying", return_value=True),
            mock.patch("utils.i18n.libretranslate.deploy") as started,
            self.assertRaises(RuntimeError),
            server(Path("/repo"), ["de"], 1),
        ):
            pass
        started.assert_not_called()

    def test_a_live_router_pid_reports_a_deploy(self) -> None:
        self.assertTrue(deploying(self._root_holding(os.getpid())))

    def test_a_stale_pid_file_reports_no_deploy(self) -> None:
        root = self._root_holding(4242)
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            self.assertFalse(deploying(root))

    def test_a_missing_pid_file_reports_no_deploy(self) -> None:
        self.assertFalse(deploying(Path(self._tmp.name)))

    def _root_holding(self, pid: int) -> Path:
        root = Path(self._tmp.name)
        (root / "build").mkdir(exist_ok=True)
        (root / "build" / "deploy.pid").write_text(str(pid))
        return root

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)


class TestTranslateFailures(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LibreTranslate("http://libretranslate", 1)

    def test_an_unreachable_server_stops_the_run(self) -> None:
        refused = urllib.error.URLError(ConnectionRefusedError())
        with (
            mock.patch.object(self.client, "_call", side_effect=refused),
            self.assertRaises(OSError),
        ):
            self.client.translate(["Hello", "World"], "de")

    def test_a_rejected_request_discards_only_its_texts(self) -> None:
        rejected = urllib.error.HTTPError(
            "http://libretranslate", 500, "boom", {}, None
        )
        with mock.patch.object(self.client, "_call", side_effect=rejected):
            self.assertEqual(
                self.client.translate(["Hello", "World"], "de"), [None, None]
            )


class TestAccelerated(unittest.TestCase):
    def _runtimes(self, stdout: str) -> mock.Mock:
        return mock.Mock(spec=subprocess.CompletedProcess, stdout=stdout)

    def test_a_registered_nvidia_runtime_enables_the_gpu(self) -> None:
        listed = self._runtimes('{"nvidia":{"path":"nvidia-container-runtime"}}')
        with mock.patch("subprocess.run", return_value=listed):
            self.assertTrue(accelerated())

    def test_a_host_without_the_toolkit_falls_back_to_the_cpu(self) -> None:
        listed = self._runtimes('{"runc":{"path":"runc"}}')
        with mock.patch("subprocess.run", return_value=listed):
            self.assertFalse(accelerated())

    def test_an_unavailable_docker_falls_back_to_the_cpu(self) -> None:
        with mock.patch("subprocess.run", return_value=self._runtimes("")):
            self.assertFalse(accelerated())


if __name__ == "__main__":
    unittest.main()
