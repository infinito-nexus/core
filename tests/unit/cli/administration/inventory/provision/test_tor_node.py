import tempfile
import unittest
from pathlib import Path

import utils.handler.vault  # noqa: F401  registers the !vault YAML constructor
from cli.administration.inventory.provision.tor_node import apply_tor_node_onion
from cli.administration.inventory.provision.yaml_io import load_yaml

_VAULT_CRED = """\
applications:
  svc-db-openldap:
    credentials:
      administrator_database_password: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        33323532656330393531653863306437306438353765363637326435636235396237
        3435626336306666643833633030333736316234623365610a303233663130636566
"""


class TestApplyTorNodeOnion(unittest.TestCase):
    def test_writes_node_when_svc_net_tor_deployed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            hv = base / "host_vars.yml"
            apply_tor_node_onion(
                host_vars_file=hv,
                application_ids=["web-app-x", "svc-net-tor"],
                base_dir=base,
            )
            data = load_yaml(hv)
            node = data["applications"]["svc-net-tor"]["services"]["tor"]["node"]
            self.assertTrue(node.endswith(".onion"))
            # The key files are minted under base/.onion-identity/hs (the SPOT).
            self.assertTrue((base / ".onion-identity" / "hs" / "hostname").exists())

    def test_reuses_existing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            hv = base / "host_vars.yml"
            for _ in range(2):
                apply_tor_node_onion(
                    host_vars_file=hv,
                    application_ids=["svc-net-tor"],
                    base_dir=base,
                )
            node = load_yaml(hv)["applications"]["svc-net-tor"]["services"]["tor"][
                "node"
            ]
            hs_file = base / ".onion-identity" / "hs" / "hostname"
            hostname = hs_file.read_text(
                encoding="ascii"
            ).strip()  # nocheck: cache-read -- tempdir
            self.assertEqual(node, hostname)

    def test_preserves_existing_vault_credentials(self) -> None:
        """Writing tor.node must not strip !vault tags from credentials that
        already live in the same host_vars file — otherwise the ciphertext is
        re-emitted as an untagged plain string and never decrypts."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            hv = base / "host_vars.yml"
            hv.write_text(_VAULT_CRED, encoding="utf-8")
            apply_tor_node_onion(
                host_vars_file=hv,
                application_ids=["svc-db-openldap", "svc-net-tor"],
                base_dir=base,
            )
            out = hv.read_text(encoding="utf-8")  # nocheck: cache-read -- tempdir
            self.assertIn("!vault |", out)
            self.assertNotIn("administrator_database_password: '$ANSIBLE_VAULT", out)

    def test_noop_when_svc_net_tor_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            hv = base / "host_vars.yml"
            apply_tor_node_onion(
                host_vars_file=hv,
                application_ids=["web-app-x"],
                base_dir=base,
            )
            self.assertFalse(hv.exists())


if __name__ == "__main__":
    unittest.main()
