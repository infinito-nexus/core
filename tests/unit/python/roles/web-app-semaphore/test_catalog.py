from __future__ import annotations

import copy
import importlib.util
import json
import unittest

import jinja2
from ansible.errors import AnsibleFilterError

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = "web-app-semaphore"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
INTERFACE = json.loads(
    read_text(str(ROLE_DIR / "files" / "opentofu" / "interface.json"))
)
SERVICES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))
DEFAULTS = SERVICES["semaphore"]["workspaces"]["catalog"]
HOST_GROUPS = {"proxmox": "web-app-proxmox", "incus": "svc-virt-incus"}
PROXMOX = {
    "cloud": {
        "sizes": {"tiny": {"cores": 1, "memory": 1024, "disk": 10}},
        "regions": {"lab": {"host": "lab", "node": "lab", "kvm": True}},
    }
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalog = _load(
    "semaphore_catalog", ROLE_DIR / "filter_plugins" / "semaphore_catalog.py"
)
schema = _load(
    "semaphore_provision_schema",
    ROLE_DIR / "files" / "python" / "provision" / "schema.py",
)


def host_expression(group):
    return f"{{{{ groups.get('{group}', []) | first | default('') }}}}"


def inventory(**providers):
    """Args:
        providers: ``provider=catalog`` the inventory sets.

    Returns:
        The inventory's ``applications`` overrides.
    """
    return {ROLE: {"services": {"semaphore": {"workspaces": {"catalog": providers}}}}}


def effective(**providers):
    """Args:
        providers: ``provider=catalog`` the inventory sets.

    Returns:
        The filter's result on the catalogs the config lookup would return.
    """
    applications = inventory(**providers)
    merged = merge_with_defaults(
        {ROLE: {"services": copy.deepcopy(SERVICES)}}, applications
    )
    services = merged[ROLE]["services"]
    return catalog.semaphore_catalogs(
        services["semaphore"]["workspaces"]["catalog"], applications, ROLE
    )


class TestDefaults(unittest.TestCase):
    def test_only_proven_catalogs_have_defaults(self):
        rule = schema.definition(INTERFACE, "catalog")
        self.assertEqual(set(DEFAULTS), set(catalog.PROVIDERS))
        for provider in ("incus", "proxmox"):
            with self.subTest(provider=provider):
                self.assertTrue(DEFAULTS[provider])
                schema.check(DEFAULTS[provider], rule, provider)
        for provider in ("hetzner", "ionos", "scs"):
            with self.subTest(provider=provider):
                self.assertEqual(DEFAULTS[provider], {})

    def test_the_virt_defaults_offer_one_demo_size_on_the_first_group_host(self):
        demo = {"vcpus": 1, "memory_mib": 2048, "disk_gib": 20}
        for provider, group in HOST_GROUPS.items():
            for flavor, offer in DEFAULTS[provider].items():
                with self.subTest(provider=provider, flavor=flavor):
                    self.assertEqual(offer["sizes"], {"demo": demo})
                    for region in offer["regions"].values():
                        self.assertEqual(region["host"], host_expression(group))
        regions = DEFAULTS["proxmox"]["cloud"]["regions"]
        self.assertEqual(
            {name: region["kvm"] for name, region in regions.items()},
            {"pve": True, "pve-emulated": False},
        )
        for region in regions.values():
            self.assertEqual(
                (region["node"], region["storage"], region["bridge"]),
                ("pve", "local-lvm", "vmbr0"),
            )
            self.assertEqual(region["templates"], {"kvm": 9000, "emulated": 9001})
        for offer in DEFAULTS["incus"].values():
            self.assertEqual(
                offer["regions"],
                {
                    "default": {
                        "host": host_expression("svc-virt-incus"),
                        "pool": "agents",
                    }
                },
            )

    def test_the_host_renders_without_its_group_so_other_deploys_keep_running(self):
        strict = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=jinja2.select_autoescape(default_for_string=False),
        )
        for group in HOST_GROUPS.values():
            with self.subTest(group=group):
                template = strict.from_string(host_expression(group))
                self.assertEqual(
                    template.render(groups={group: ["h1.lan", "h2"]}), "h1.lan"
                )
                self.assertEqual(template.render(groups={}), "")
                bare = strict.from_string(f"{{{{ groups['{group}'] | first }}}}")
                with self.assertRaises(jinja2.UndefinedError):
                    bare.render(groups={})


class TestInventory(unittest.TestCase):
    def test_an_inventory_catalog_replaces_the_default(self):
        applications = inventory(proxmox=PROXMOX)
        merged = merge_with_defaults(
            {ROLE: {"services": copy.deepcopy(SERVICES)}}, applications
        )[ROLE]["services"]["semaphore"]["workspaces"]["catalog"]
        self.assertIn("demo", merged["proxmox"]["cloud"]["sizes"])
        result = catalog.semaphore_catalogs(merged, applications, ROLE)
        self.assertEqual(result["proxmox"], PROXMOX)
        for provider in ("hetzner", "ionos", "scs", "incus"):
            self.assertEqual(result[provider], DEFAULTS[provider])
        self.assertEqual(catalog.semaphore_catalogs(DEFAULTS, {}, ROLE), DEFAULTS)

    def test_an_invalid_catalog_fails_the_deploy(self):
        sizes = {"small": {}}
        regions = {"fra": {}}
        cases = {
            "<root>": ([], "hetzner: is not of type object"),
            "flavor": ({"edge": {}}, "hetzner.edge: is not one of"),
            "flavor entry": ({"cloud": []}, "hetzner.cloud: is not of type object"),
            "sizes missing": (
                {"cloud": {"regions": regions}},
                "hetzner.cloud.sizes: is missing",
            ),
            "regions missing": (
                {"cloud": {"sizes": sizes}},
                "hetzner.cloud.regions: is missing",
            ),
            "sizes type": (
                {"cloud": {"sizes": [], "regions": regions}},
                "hetzner.cloud.sizes: is not of type object",
            ),
            "sizes empty": (
                {"cloud": {"sizes": {}, "regions": regions}},
                "hetzner.cloud.sizes: holds fewer than 1 keys",
            ),
            "size name": (
                {"cloud": {"sizes": {"Small": {}}, "regions": regions}},
                "hetzner.cloud.sizes.Small: does not match",
            ),
            "size entry": (
                {"cloud": {"sizes": {"small": 1}, "regions": regions}},
                "hetzner.cloud.sizes.small: is not of type object",
            ),
            "regions type": (
                {"cloud": {"sizes": sizes, "regions": "fra"}},
                "hetzner.cloud.regions: is not of type object",
            ),
            "regions empty": (
                {"cloud": {"sizes": sizes, "regions": {}}},
                "hetzner.cloud.regions: holds fewer than 1 keys",
            ),
            "region name": (
                {"cloud": {"sizes": sizes, "regions": {"fra_1": {}}}},
                "hetzner.cloud.regions.fra_1: does not match",
            ),
            "region entry": (
                {"cloud": {"sizes": sizes, "regions": {"fra": "x"}}},
                "hetzner.cloud.regions.fra: is not of type object",
            ),
        }
        for case, (value, message) in cases.items():
            with self.subTest(case=case):
                with self.assertRaises(AnsibleFilterError) as caught:
                    effective(hetzner=value)
                self.assertIn(
                    f"services.semaphore.workspaces.catalog.{message}",
                    str(caught.exception),
                )

    def test_a_region_two_providers_offer_fails_the_deploy(self):
        twin = {"cloud": {"sizes": {"small": {}}, "regions": {"pve": {}}}}
        with self.assertRaisesRegex(
            AnsibleFilterError,
            "region 'pve' of flavor cloud is offered by ionos, proxmox",
        ):
            effective(ionos=twin)

    def test_an_unknown_provider_fails_the_deploy(self):
        with self.assertRaisesRegex(AnsibleFilterError, "names the providers"):
            effective(vultr={})


if __name__ == "__main__":
    unittest.main()
