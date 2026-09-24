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
        with (
            mock.patch("utils.i18n.libretranslate.time.sleep"),
            mock.patch.object(self.client, "_call", side_effect=rejected),
        ):
            self.assertEqual(
                self.client.translate(["Hello", "World"], "de").values, [None, None]
            )


class TestRefusalsAreRetried(unittest.TestCase):
    """A server that buckles under the lanes must not cost entries for good."""

    def setUp(self) -> None:
        self.client = LibreTranslate("http://libretranslate", 1)
        self.refusal = urllib.error.HTTPError(
            "http://libretranslate", 500, "boom", {}, None
        )

    def test_a_transient_refusal_is_retried_until_it_succeeds(self) -> None:
        answers = [self.refusal, self.refusal, {"translatedText": ["Hallo"]}]
        with (
            mock.patch("utils.i18n.libretranslate.time.sleep"),
            mock.patch.object(self.client, "_call", side_effect=answers),
        ):
            outcome = self.client.translate(["Hello"], "de")

        self.assertEqual(outcome.values, ["Hallo"])
        self.assertEqual(outcome.refused, 2)
        self.assertEqual(outcome.damaged, 0)

    def test_a_permanent_refusal_is_counted_and_named(self) -> None:
        with (
            mock.patch("utils.i18n.libretranslate.time.sleep"),
            mock.patch.object(self.client, "_call", side_effect=self.refusal),
        ):
            outcome = self.client.translate(["Hello"], "de")

        self.assertEqual(outcome.values, [None])
        self.assertTrue(outcome.refused)
        self.assertIn("HTTPError", outcome.refusal)

    def test_a_catalog_never_inherits_another_lane_s_counts(self) -> None:
        answers = [
            self.refusal,
            {"translatedText": ["Hallo"]},
            {"translatedText": ["Hi"]},
        ]
        with (
            mock.patch("utils.i18n.libretranslate.time.sleep"),
            mock.patch.object(self.client, "_call", side_effect=answers),
        ):
            first = self.client.translate(["Hello"], "de")
            second = self.client.translate(["Hello"], "de")

        self.assertEqual(first.refused, 1)
        self.assertEqual(second.refused, 0)


class TestScriptedTargetCodes(unittest.TestCase):
    """LibreTranslate offers Chinese as zh-Hans/zh-Hant, never as bare zh."""

    def setUp(self) -> None:
        self.client = LibreTranslate("http://libretranslate", 1)
        self.served = [{"code": "en", "targets": ["de", "zh-Hans", "zh-Hant"]}]

    def test_the_catalog_code_is_sent_as_the_code_the_server_serves(self) -> None:
        with mock.patch.object(
            self.client, "_call", return_value={"translatedText": ["你好"]}
        ) as call:
            self.client.translate(["Hello"], "zh")

        self.assertEqual(call.call_args.args[1]["target"], "zh-Hans")

    def test_waiting_accepts_a_server_that_only_names_the_script(self) -> None:
        with mock.patch.object(self.client, "_call", return_value=self.served):
            self.client.wait(["zh", "de"], timeout=0)

    def test_waiting_still_reports_a_target_nobody_serves(self) -> None:
        with (
            mock.patch.object(self.client, "_call", return_value=self.served),
            self.assertRaises(TimeoutError) as raised,
        ):
            self.client.wait(["fr"], timeout=0)

        self.assertIn("fr", str(raised.exception))


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
