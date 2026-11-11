import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import utils.handler.vault  # noqa: F401  registers the !vault YAML constructor
from cli.administration.inventory.provision.network_mode import (
    apply_network_mode_from_env,
)
from cli.administration.inventory.provision.yaml_io import load_yaml

_VAULT_CRED = """\
applications:
  svc-db-mariadb:
    credentials:
      root_password: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        33323532656330393531653863306437306438353765363637326435636235396237
        3435626336306666643833633030333736316234623365610a303233663130636566
"""


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

    def test_preserves_existing_vault_credentials(self) -> None:
        """Writing NETWORK_MODE must not strip !vault tags from credentials that
        already live in the same host_vars file — otherwise the ciphertext is
        re-emitted as an untagged plain string and every consumer receives it
        verbatim instead of the secret."""
        hv = self._apply("multi", _VAULT_CRED)
        out = hv.read_text(encoding="utf-8")  # nocheck: cache-read -- tempdir
        self.assertIn("!vault |", out)
        self.assertNotIn("root_password: '$ANSIBLE_VAULT", out)

    def test_noop_without_the_variable(self) -> None:
        self.assertFalse(self._apply(None).exists())

    def test_an_unknown_mode_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            self._apply("onion")


if __name__ == "__main__":
    unittest.main()
