from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ._fake_provision import INTERFACE, PUBLIC_KEY, WORKSPACE, ZONE, load

inputs = load("provision.inputs")

REGION = {"host": "pve", "node": "pve"}
VALUES = {
    "name": "SO-1-1",
    "flavor": "cloud",
    "size": "small",
    "region": "fra",
    "ssh_public_key": PUBLIC_KEY,
    "dns_label": "shop",
}


def catalogs(**offered):
    """Args:
        offered: ``provider={flavor: {"sizes": ..., "regions": ...}}``.

    Returns:
        A catalog per provider, empty where none is given.
    """
    return {provider: offered.get(provider, {}) for provider in inputs.PROVIDERS}


def cloud(*regions, sizes=("small",)):
    """Args:
        regions: the region keys of the ``cloud`` flavor.
        sizes: its size keys.

    Returns:
        A one-flavor catalog.
    """
    return {
        "cloud": {
            "sizes": {size: {} for size in sizes},
            "regions": {region: dict(REGION) for region in regions},
        }
    }


class TempCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


class TestSelectProvider(unittest.TestCase):
    def test_the_one_provider_offering_the_region_is_selected(self):
        offered = catalogs(proxmox=cloud("pve"), hetzner=cloud("fra"))
        self.assertEqual(inputs.select_provider(offered, VALUES), "hetzner")

    def test_a_region_offered_twice_is_refused(self):
        offered = catalogs(hetzner=cloud("fra"), ionos=cloud("fra"))
        with self.assertRaisesRegex(inputs.RefusedError, "offered by hetzner, ionos"):
            inputs.select_provider(offered, VALUES)

    def test_an_unoffered_region_names_the_empty_catalogs(self):
        offered = catalogs(proxmox=cloud("pve"))
        with self.assertRaisesRegex(
            inputs.RefusedError, "empty catalogs: hetzner, ionos, scs, incus"
        ):
            inputs.select_provider(offered, VALUES)

    def test_a_size_the_provider_lacks_is_refused(self):
        offered = catalogs(hetzner=cloud("fra", sizes=("large",)))
        with self.assertRaisesRegex(
            inputs.RefusedError, "hetzner catalog offers no size"
        ):
            inputs.select_provider(offered, VALUES)


class TestTargets(unittest.TestCase):
    def test_pairs_yield_canonical_hosts(self):
        self.assertEqual(
            inputs.target_hosts(" 192.0.2.1:22, [2001:DB8::1]:2222,box.example:22,"),
            {"192.0.2.1", "2001:db8::1", "box.example"},
        )

    def test_a_malformed_pair_is_refused(self):
        for text in ("192.0.2.1", "192.0.2.1:0", "192.0.2.1:65536", ":22", "a:b"):
            with self.subTest(text=text), self.assertRaises(inputs.RefusedError):
                inputs.target_hosts(text)

    def test_an_address_with_a_zone_index_is_refused(self):
        self.assertEqual(inputs.address("2001:DB8::1", "HOST"), "2001:db8::1")
        with self.assertRaisesRegex(inputs.RefusedError, "HOST"):
            inputs.address("fe80::1%eth0", "HOST")


class TestRecordTarget(unittest.TestCase):
    def test_an_address_or_a_host_name_of_the_targets_is_taken(self):
        env = {
            "DNS_ACTION": "create",
            "SALES_ORDER": "SO-1",
            "LINE": "1",
            "DNS_LABEL": "shop",
            "WORKSPACE_TARGETS": "box.example.org:22,[2001:db8::1]:22",
        }
        named = inputs.dns_request({**env, "HOST": "box.example.org"}, INTERFACE)
        self.assertEqual((named["host"], named["cname"]), ("", "box.example.org"))
        addressed = inputs.dns_request({**env, "HOST": "2001:DB8::1"}, INTERFACE)
        self.assertEqual((addressed["host"], addressed["cname"]), ("2001:db8::1", ""))
        with self.assertRaisesRegex(inputs.RefusedError, "WORKSPACE_TARGETS"):
            inputs.dns_request({**env, "HOST": "other.example.org"}, INTERFACE)

    def test_a_malformed_host_name_is_refused(self):
        for value in (
            "box",
            "Box.example.org",
            "box.example.org.",
            "-box.example.org",
            "box..example.org",
            "box.example.1",
            "fe80::1%eth0",
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(inputs.RefusedError, "^HOST"),
            ):
                inputs.record_target(value, INTERFACE)


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.env = {"WORKSPACE": WORKSPACE, "WORKSPACE_DNS_ZONE": ZONE}

    def test_the_zone_id_follows_the_flavor(self):
        self.assertEqual(
            inputs.workspace_document(self.env, INTERFACE, "knot")["dns"],
            {"zone": ZONE, "zone_id": ""},
        )
        routed = {**self.env, "WORKSPACE_DNS_ZONE_ID": "Z0123456789"}
        self.assertEqual(
            inputs.workspace_document(routed, INTERFACE, "route53")["dns"]["zone_id"],
            "Z0123456789",
        )
        for env, flavor in ((self.env, "cloudflare"), (routed, "knot")):
            with self.subTest(flavor=flavor), self.assertRaises(inputs.RefusedError):
                inputs.workspace_document(env, INTERFACE, flavor)

    def test_a_malformed_workspace_names_its_variable(self):
        with self.assertRaisesRegex(inputs.RefusedError, "^WORKSPACE "):
            inputs.workspace_document({**self.env, "WORKSPACE": "x"}, INTERFACE, "knot")


class TestCheckout(TempCase):
    def test_every_code_and_cli_config_name_is_found_outside_git(self):
        for relative in (
            "a/main.TF",
            "b/x.tofu.json",
            ".tofurc",
            "c/.terraformrc",
            "d.tf",
            ".git/hooks/x.tf",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (self.root / "provision" / "e.tf").mkdir(parents=True)
        self.assertEqual(
            inputs.refused_files(self.root),
            [
                ".tofurc",
                "a/main.TF",
                "b/x.tofu.json",
                "c/.terraformrc",
                "d.tf",
                "provision/e.tf",
            ],
        )

    def test_a_tfvars_file_reached_through_a_symlink_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "SO-1-1.tfvars.json").write_text(
            json.dumps(VALUES), encoding="utf-8"
        )
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / "provision").symlink_to(outside)
        with self.assertRaisesRegex(inputs.RefusedError, "no regular file"):
            inputs.load_tfvars(checkout, "SO-1-1", INTERFACE)
        (checkout / "provision").unlink()
        (checkout / "provision").mkdir()
        (checkout / "provision" / "SO-1-1.tfvars.json").write_text(
            json.dumps(VALUES), encoding="utf-8"
        )
        self.assertEqual(inputs.load_tfvars(checkout, "SO-1-1", INTERFACE), VALUES)


class TestCatalogs(TempCase):
    def write(self, provider, text):
        (self.root / f"{provider}.json").write_text(text, encoding="utf-8")

    def test_every_provider_catalog_is_loaded_and_checked(self):
        for provider in inputs.PROVIDERS:
            self.write(provider, "{}")
        self.write("hetzner", json.dumps(cloud("fra")))
        self.assertEqual(
            inputs.load_catalogs(self.root, INTERFACE)["hetzner"], cloud("fra")
        )
        self.write("hetzner", json.dumps({"edge": {}}))
        with self.assertRaisesRegex(inputs.RefusedError, "^hetzner"):
            inputs.load_catalogs(self.root, INTERFACE)
        self.write("hetzner", "{")
        with self.assertRaisesRegex(inputs.RefusedError, "hetzner.json is no JSON"):
            inputs.load_catalogs(self.root, INTERFACE)
        (self.root / "hetzner.json").unlink()
        with self.assertRaisesRegex(inputs.RefusedError, "holds no hetzner.json"):
            inputs.load_catalogs(self.root, INTERFACE)


if __name__ == "__main__":
    unittest.main()
