import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.i18n import gateway
from utils.inventory import tools_idle

SHARED = "http://127.0.0.1:8080"
OWN = "http://127.0.0.1:9090"


class _Stamped(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.stamps = Path(tmp.name) / "tools"
        patcher = mock.patch.object(gateway, "stamp_dir", return_value=self.stamps)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_stamped_once_finished(self) -> None:
        self.assertTrue((self.stamps / tools_idle.LAST).is_file())
        self.assertFalse(tools_idle.running(self.stamps))

    def assert_not_stamped(self) -> None:
        self.assertFalse((self.stamps / tools_idle.LAST).exists())


class TestSharedGateway(_Stamped):
    def test_a_shared_gateway_that_serves_is_used_without_a_deploy(self) -> None:
        with (
            mock.patch.object(gateway, "serving", return_value=SHARED),
            mock.patch.object(gateway, "deploy") as deployed,
            mock.patch.object(gateway, "unaccelerated") as stamped,
            gateway.server(Path("/repo"), shared=SHARED) as url,
        ):
            self.assertEqual(url, SHARED)
        deployed.assert_not_called()
        stamped.assert_not_called()

    def test_a_run_against_the_shared_gateway_is_stamped_while_it_runs(self) -> None:
        with (
            mock.patch.object(gateway, "serving", return_value=SHARED),
            gateway.server(Path("/repo"), shared=SHARED),
        ):
            self.assertTrue(tools_idle.running(self.stamps))
        self.assert_stamped_once_finished()

    def test_a_shared_gateway_that_names_no_language_stops_the_run(self) -> None:
        with (
            mock.patch.object(gateway, "serving", return_value=""),
            mock.patch.object(gateway, "deploy") as deployed,
            self.assertRaises(RuntimeError),
            gateway.server(Path("/repo"), shared=SHARED),
        ):
            pass
        deployed.assert_not_called()
        self.assert_not_stamped()

    def test_a_shared_gateway_is_never_redeployed_from_here(self) -> None:
        with (
            mock.patch.object(gateway, "deploy") as deployed,
            self.assertRaises(RuntimeError),
            gateway.server(Path("/repo"), redeploy=True, shared=SHARED),
        ):
            pass
        deployed.assert_not_called()
        self.assert_not_stamped()


class TestOwnGateway(_Stamped):
    def test_a_run_against_the_own_gateway_is_stamped_while_it_runs(self) -> None:
        with (
            mock.patch.object(gateway, "deploying", return_value=False),
            mock.patch.object(gateway, "unaccelerated", return_value=False),
            mock.patch.object(gateway, "deployed", return_value=OWN),
            mock.patch.object(gateway, "deploy") as deployed,
            gateway.server(Path("/repo")) as url,
        ):
            self.assertEqual(url, OWN)
            self.assertTrue(tools_idle.running(self.stamps))
        deployed.assert_not_called()
        self.assert_stamped_once_finished()

    def test_a_run_refused_for_a_running_deploy_is_not_stamped(self) -> None:
        with (
            mock.patch.object(gateway, "deploying", return_value=True),
            self.assertRaises(RuntimeError),
            gateway.server(Path("/repo")),
        ):
            pass
        self.assert_not_stamped()


if __name__ == "__main__":
    unittest.main()
