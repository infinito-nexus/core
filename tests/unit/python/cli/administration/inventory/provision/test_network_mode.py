import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.inventory.provision.network_mode import (
    apply_network_mode_from_env,
)
from cli.administration.inventory.provision.yaml_io import load_yaml


class TestApplyNetworkModeFromEnv(unittest.TestCase):
    def _apply(self, network: str | None, existing: str = "") -> Path:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        hv = Path(tmp) / "host_vars.yml"
        if existing:
            hv.write_text(existing, encoding="utf-8")
        env = {} if network is None else {"network": network}
        with mock.patch.dict("os.environ", env, clear=True):
            apply_network_mode_from_env(hv)
        return hv

    def test_writes_the_row_network_mode(self) -> None:
        hv = self._apply("tor", "applications: {}\n")
        self.assertEqual(load_yaml(hv)["NETWORK_MODE"], "tor")
        self.assertEqual(load_yaml(hv)["applications"], {})

    def test_noop_without_the_variable(self) -> None:
        self.assertFalse(self._apply(None).exists())

    def test_an_unknown_mode_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            self._apply("onion")


if __name__ == "__main__":
    unittest.main()
