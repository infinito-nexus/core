import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.tor_node import apply_tor_node_onion
from cli.administration.inventory.provision.yaml_io import load_yaml


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
            hostname = hs_file.read_text(encoding="ascii").strip()  # nocheck: cache-read -- tempdir
            self.assertEqual(node, hostname)

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
