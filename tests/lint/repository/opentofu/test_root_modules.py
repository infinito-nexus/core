from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
OPENTOFU = ROLE / "files" / "opentofu"
PYTHON = ROLE / "files" / "python"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
ROOTS = ("hetzner", "ionos", "scs", "proxmox", "incus")
DNS_FLAVORS = ("knot", "route53", "cloudflare")
DNS_INPUTS = frozenset({"zone", "zone_id", "name", "ipv4", "ipv6", "cname"})
DNS_OUTPUTS = frozenset({"fqdn"})
RECORD_INPUTS = frozenset({"dns_label", "host", "cname"})
CNAME_COUNT = '${var.cname != "" ? 1 : 0}'
IMAGE_FREE = frozenset({"catalog.json", "workspace.json", ".terraform"})
DNS_PROVIDERS = frozenset({"dns", "aws", "cloudflare"})
NODE_SSH_KEYS = frozenset(
    {
        "ssh",
        "source_file",
        "idmap",
        "user_data_file_id",
        "vendor_data_file_id",
        "meta_data_file_id",
        "network_data_file_id",
    }
)
NODE_SSH_RESOURCES = frozenset({"proxmox_virtual_environment_file"})
CATALOG_REGION = "${local.catalog.regions[var.region]}"

_BLOCKS = (
    "terraform",
    "variable",
    "output",
    "locals",
    "resource",
    "module",
    "provider",
)
_EXACT = re.compile(r"^=?\s*\d+\.\d+\.\d+$")
_LOCKED = re.compile(
    r'provider "registry\.opentofu\.org/([^"]+)" \{\s*version\s*=\s*"([^"]+)"'
)
_TERNARY = re.compile(r'^\$\{local\.region\.kvm \? "([^"]+)" : "([^"]+)"\}$')
_REGION = re.compile(r"^\$\{local\.region\.([a-z_]+)\}$")
_INDEX = re.compile(r"^\$\{local\.region\.([a-z_]+)\[local\.([a-z_]+)\]\}$")
_LOCAL = re.compile(r"^\$\{local\.([a-z_]+)\}$")


def load_module(directory: Path) -> dict:
    """Args:
        directory: module directory holding ``*.tf.json`` files.

    Returns:
        Block name to merged body; resources keyed by type, then name.
    """
    merged: dict = {block: {} for block in _BLOCKS}
    for path in sorted(directory.glob("*.tf.json")):
        for block, body in json.loads(read_text(str(path))).items():
            if block == "resource":
                for kind, named in body.items():
                    merged[block].setdefault(kind, {}).update(named)
            else:
                merged[block].update(body)
    return merged


def interface() -> dict:
    return json.loads(read_text(str(OPENTOFU / "interface.json")))


def _dns_sources() -> set[str]:
    return {
        spec["source"]
        for flavor in DNS_FLAVORS
        for spec in load_module(OPENTOFU / "modules" / f"dns-{flavor}")["terraform"][
            "required_providers"
        ].values()
    }


def _locked(directory: Path) -> dict[str, str]:
    lock = directory / ".terraform.lock.hcl"
    if not lock.is_file():
        return {}
    return dict(_LOCKED.findall(read_text(str(lock))))


def _pin_findings(directory: Path, module: dict) -> list[str]:
    pins = {
        name: (spec["source"], spec.get("version", ""))
        for name, spec in module["terraform"].get("required_providers", {}).items()
    }
    locked = _locked(directory)
    findings = [
        f"provider {name} pins {version!r}, not one exact version"
        for name, (_, version) in pins.items()
        if not _EXACT.match(version)
    ]
    findings += [
        f"lock file lacks {source} {version}"
        for source, version in pins.values()
        if locked.get(source) != version.lstrip("= ")
    ]
    pinned = {source for source, _ in pins.values()}
    findings += [
        f"DNS flavor provider {source} is not pinned by the root"
        for source in sorted(_dns_sources() - pinned)
    ]
    return findings


def _backend_findings(module: dict) -> list[str]:
    s3 = module["terraform"].get("backend", {}).get("s3")
    if not isinstance(s3, dict):
        return ["no S3 backend"]
    if s3.get("use_lockfile") is not True:
        return ["S3 backend without use_lockfile"]
    return []


def services_catalog(provider: str) -> dict:
    """Args:
        provider: a root name.

    Returns:
        The default catalog of that root in ``meta/services.yml``.
    """
    services = load_yaml_str(read_text(str(SERVICES)))
    return services["semaphore"]["workspaces"]["catalog"][provider]


def load_inputs_module():
    sys.path.insert(0, str(PYTHON))
    try:
        spec = spec_from_file_location(
            "provision_inputs", PYTHON / "provision" / "inputs.py"
        )
        module = module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PYTHON))
    return module


def interface_findings(directory: Path) -> list[str]:
    """Args:
        directory: root module directory.

    Returns:
        Findings; empty when the root implements the interface.
    """
    spec = interface()
    module = load_module(directory)
    variables, outputs = module["variable"], module["output"]
    findings = []
    if set(variables) != set(spec["properties"]):
        findings.append(
            f"variables {sorted(variables)} != {sorted(spec['properties'])}"
        )
    findings += [
        f"variable {name} is not a string"
        for name, body in variables.items()
        if body.get("type") != "string"
    ]
    if set(outputs) != set(spec["outputs"]):
        findings.append(f"outputs {sorted(outputs)} != {sorted(spec['outputs'])}")
    findings += _pin_findings(directory, module)
    findings += _backend_findings(module)
    shipped = sorted(p.name for p in directory.iterdir() if p.name in IMAGE_FREE)
    return findings + [f"ships {name} beside the root" for name in shipped]


def records_findings(directory: Path) -> list[str]:
    """Args:
        directory: the record root of ``dns ws-<id>``.

    Returns:
        Findings; empty when it takes a label, a host and a cname, returns ``fqdn``,
        pins its providers and keeps its state in the locked S3 backend.
    """
    module = load_module(directory)
    findings = []
    if set(module["variable"]) != RECORD_INPUTS:
        findings.append(f"variables {sorted(module['variable'])}")
    if set(module["output"]) != DNS_OUTPUTS:
        findings.append(f"outputs {sorted(module['output'])}")
    if module["resource"]:
        findings.append(f"declares resources {sorted(module['resource'])}")
    return findings + _pin_findings(directory, module) + _backend_findings(module)


def dns_findings(directory: Path) -> list[str]:
    """Args:
        directory: root module directory.

    Returns:
        Findings; empty when the record comes from the module alone.
    """
    module = load_module(directory)
    call = module["module"].get("dns")
    findings = [
        f"declares the DNS resource {kind}"
        for kind in module["resource"]
        if kind.split("_", 1)[0] in DNS_PROVIDERS
    ]
    if not isinstance(call, dict) or call.get("source") != "./modules/dns":
        return [*findings, "no module dns sourced from ./modules/dns"]
    passed = set(call) - {"source"}
    if passed != DNS_INPUTS:
        findings.append(f"module dns gets {sorted(passed)}, not {sorted(DNS_INPUTS)}")
    return findings


def cname_findings(module: dict) -> list[str]:
    """Args:
        module: a loaded DNS flavor module.

    Returns:
        Findings; empty when exactly one resource writes a CNAME, only while
        ``cname`` is set and to the name it holds, and no other resource
        reads ``cname``.
    """
    records = [body for named in module["resource"].values() for body in named.values()]
    cnames = [
        body
        for kind, named in module["resource"].items()
        for body in named.values()
        if kind == "dns_cname_record" or body.get("type") == "CNAME"
    ]
    if len(cnames) != 1:
        return [f"{len(cnames)} CNAME resources"]
    (cname,) = cnames
    findings = []
    if cname.get("count") != CNAME_COUNT:
        findings.append(f"the CNAME count is {cname.get('count')!r}")
    target = cname.get("cname") or cname.get("content") or cname.get("records")
    if "${var.cname}" not in json.dumps(target):
        findings.append(f"the CNAME points to {target!r}")
    if any(body is not cname and "var.cname" in json.dumps(body) for body in records):
        findings.append("an address record reads cname")
    return findings


def _resolve(expression: object, region: dict, local: dict) -> object:
    text = str(expression)
    if match := _TERNARY.match(text):
        return match.group(1) if region["kvm"] else match.group(2)
    if match := _REGION.match(text):
        return region[match.group(1)]
    if match := _INDEX.match(text):
        key = _resolve(local[match.group(2)], region, local)
        return region[match.group(1)][key]
    if match := _LOCAL.match(text):
        return _resolve(local[match.group(1)], region, local)
    raise ValueError(f"{text!r} is not rendered from the region")


def render_vm(module: dict, region: dict) -> dict:
    """Args:
        module: merged proxmox root.
        region: catalog region with node, storage, bridge, kvm and templates.

    Returns:
        The node, storages, bridge, cloned template, full clone flag and CPU type.
    """
    vm = module["resource"]["proxmox_virtual_environment_vm"]["server"]
    local = module["locals"]
    clone, disk, init = vm["clone"][0], vm["disk"][0], vm["initialization"][0]
    storages = (clone["datastore_id"], disk["datastore_id"], init["datastore_id"])
    return {
        "node": _resolve(vm["node_name"], region, local),
        "storage": {_resolve(s, region, local) for s in storages},
        "bridge": _resolve(vm["network_device"][0]["bridge"], region, local),
        "template": _resolve(clone["vm_id"], region, local),
        "full": clone.get("full") is True,
        "cpu": _resolve(vm["cpu"][0]["type"], region, local),
    }


def kvm_findings(directory: Path) -> list[str]:
    """Args:
        directory: proxmox root module directory.

    Returns:
        Findings; empty when node, storage, bridge and kvm follow the region.
    """
    module = load_module(directory)
    findings = []
    if module["locals"].get("region") != CATALOG_REGION:
        findings.append("the region is not read from the catalog")
    for kvm, template, cpu in ((True, 1, "x86-64-v2-AES"), (False, 2, "qemu64")):
        region = {
            "node": "n",
            "storage": "s",
            "bridge": "b",
            "kvm": kvm,
            "templates": {"kvm": 1, "emulated": 2},
        }
        expected = {
            "node": "n",
            "storage": {"s"},
            "bridge": "b",
            "template": template,
            "full": True,
            "cpu": cpu,
        }
        try:
            rendered = render_vm(module, region)
        except (KeyError, IndexError, ValueError) as exc:
            findings.append(f"kvm={kvm}: {exc}")
            continue
        if rendered != expected:
            findings.append(f"kvm={kvm}: rendered {rendered}, expected {expected}")
    return findings


def _keys(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


def node_ssh_findings(directory: Path) -> list[str]:
    module = load_module(directory)
    findings = [
        f"uses {kind}" for kind in module["resource"] if kind in NODE_SSH_RESOURCES
    ]
    return findings + [
        f"sets {key}" for key in sorted(set(_keys(module)) & NODE_SSH_KEYS)
    ]


def _broken(
    root: str,
    name: str,
    change: Callable[[dict], object],
    check: Callable[[Path], list[str]],
) -> list[str]:
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / root
        shutil.copytree(OPENTOFU / "roots" / root, copy)
        document = json.loads(read_text(str(OPENTOFU / "roots" / root / name)))
        change(document)
        (copy / name).write_text(json.dumps(document), encoding="utf-8")
        return check(copy)


class TestRootModules(unittest.TestCase):
    def test_every_root_implements_the_interface(self) -> None:
        found = sorted(p.name for p in (OPENTOFU / "roots").iterdir() if p.is_dir())
        self.assertEqual(found, sorted(ROOTS))
        for root in ROOTS:
            with self.subTest(root=root):
                self.assertEqual(interface_findings(OPENTOFU / "roots" / root), [])

    def test_the_name_is_a_hostname_label_every_provider_accepts(self) -> None:
        schema = json.loads(read_text(str(OPENTOFU / "interface.json")))
        pattern = re.compile(schema["properties"]["name"]["pattern"])
        self.assertTrue(pattern.fullmatch("SAL-ORD-2026-00042-2"))
        self.assertTrue(pattern.fullmatch("S" * 63))
        for name in ("S" * 64, "1SO-2", "-SO-2", "SO-2-", "SO_2", "SO.2", ""):
            with self.subTest(name=name):
                self.assertIsNone(pattern.fullmatch(name))

    def test_negative_control_a_dropped_output_fails(self) -> None:
        def drop(document: dict) -> None:
            document["output"].pop("fqdn")

        self.assertTrue(_broken("hetzner", "outputs.tf.json", drop, interface_findings))

    def test_negative_control_an_added_variable_fails(self) -> None:
        def add(document: dict) -> None:
            document["variable"]["image"] = {"type": "string"}

        self.assertTrue(_broken("ionos", "variables.tf.json", add, interface_findings))

    def test_negative_control_a_loosened_pin_fails(self) -> None:
        def loosen(document: dict) -> None:
            document["terraform"]["required_providers"]["incus"]["version"] = "~> 1.2"

        self.assertTrue(
            _broken("incus", "versions.tf.json", loosen, interface_findings)
        )

    def test_every_dns_flavor_shares_one_contract(self) -> None:
        for flavor in DNS_FLAVORS:
            with self.subTest(flavor=flavor):
                module = load_module(OPENTOFU / "modules" / f"dns-{flavor}")
                self.assertEqual(set(module["variable"]), DNS_INPUTS)
                self.assertEqual(set(module["output"]), DNS_OUTPUTS)

    def test_every_dns_flavor_writes_a_cname_only_for_a_name(self) -> None:
        for flavor in DNS_FLAVORS:
            with self.subTest(flavor=flavor):
                module = load_module(OPENTOFU / "modules" / f"dns-{flavor}")
                self.assertEqual(cname_findings(module), [])

    def test_negative_control_a_flavor_without_a_cname_fails(self) -> None:
        module = load_module(OPENTOFU / "modules" / "dns-route53")
        module["resource"]["aws_route53_record"].pop("cname")
        self.assertTrue(cname_findings(module))

    def test_negative_control_an_unconditional_cname_fails(self) -> None:
        module = load_module(OPENTOFU / "modules" / "dns-knot")
        module["resource"]["dns_cname_record"]["record"]["count"] = 1
        self.assertTrue(cname_findings(module))

    def test_only_the_record_root_passes_a_cname(self) -> None:
        for root in ROOTS:
            with self.subTest(root=root):
                call = load_module(OPENTOFU / "roots" / root)["module"]["dns"]
                self.assertEqual(call["cname"], "")
        call = load_module(OPENTOFU / "records")["module"]["dns"]
        self.assertEqual(call["cname"], "${var.cname}")

    def test_every_root_uses_the_dns_module(self) -> None:
        for root in ROOTS:
            with self.subTest(root=root):
                self.assertEqual(dns_findings(OPENTOFU / "roots" / root), [])

    def test_negative_control_an_own_dns_resource_fails(self) -> None:
        def own(document: dict) -> None:
            document["resource"]["dns_a_record_set"] = {
                "own": {"zone": "example.org.", "name": "x", "addresses": ["192.0.2.1"]}
            }

        self.assertTrue(_broken("scs", "main.tf.json", own, dns_findings))

    def test_negative_control_a_missing_dns_module_fails(self) -> None:
        self.assertTrue(
            _broken("hetzner", "main.tf.json", lambda d: d.pop("module"), dns_findings)
        )

    def test_the_proxmox_root_takes_kvm_from_the_region(self) -> None:
        self.assertEqual(kvm_findings(OPENTOFU / "roots" / "proxmox"), [])
        catalog = services_catalog("proxmox")
        self.assertTrue(catalog)
        for flavor in catalog.values():
            for name, region in flavor["regions"].items():
                with self.subTest(region=name):
                    self.assertIsInstance(region["kvm"], bool)
                    self.assertEqual(set(region["templates"]), {"kvm", "emulated"})
                    self.assertTrue(
                        region["node"] and region["storage"] and region["bridge"]
                    )

    def test_negative_control_a_fixed_kvm_mode_fails(self) -> None:
        def fix(document: dict) -> None:
            document["locals"]["mode"] = "kvm"

        self.assertTrue(_broken("proxmox", "main.tf.json", fix, kvm_findings))

    def test_negative_control_swapped_templates_fail(self) -> None:
        def swap(document: dict) -> None:
            document["locals"]["mode"] = '${local.region.kvm ? "emulated" : "kvm"}'

        self.assertTrue(_broken("proxmox", "main.tf.json", swap, kvm_findings))

    def test_negative_control_a_linked_clone_fails(self) -> None:
        def link(document: dict) -> None:
            vm = document["resource"]["proxmox_virtual_environment_vm"]["server"]
            vm["clone"][0]["full"] = False

        self.assertTrue(_broken("proxmox", "main.tf.json", link, kvm_findings))

    def test_the_proxmox_root_needs_no_node_ssh(self) -> None:
        self.assertEqual(node_ssh_findings(OPENTOFU / "roots" / "proxmox"), [])

    def test_negative_control_a_node_ssh_block_fails(self) -> None:
        def ssh(document: dict) -> None:
            document["provider"] = {"proxmox": {"ssh": [{"agent": True}]}}

        self.assertTrue(_broken("proxmox", "main.tf.json", ssh, node_ssh_findings))

    def test_negative_control_a_catalog_beside_a_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            copy = Path(scratch) / "incus"
            shutil.copytree(OPENTOFU / "roots" / "incus", copy)
            (copy / "catalog.json").write_text("{}", encoding="utf-8")
            self.assertIn(
                "ships catalog.json beside the root", interface_findings(copy)
            )

    def test_the_record_root_holds_only_the_dns_module(self) -> None:
        self.assertEqual(records_findings(OPENTOFU / "records"), [])
        self.assertEqual(dns_findings(OPENTOFU / "records"), [])

    def test_negative_control_a_record_root_with_a_server_fails(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            copy = Path(scratch) / "records"
            shutil.copytree(OPENTOFU / "records", copy)
            main = json.loads(read_text(str(OPENTOFU / "records" / "main.tf.json")))
            main["resource"] = {"hcloud_server": {"server": {"name": "x"}}}
            (copy / "main.tf.json").write_text(json.dumps(main), encoding="utf-8")
            self.assertTrue(records_findings(copy))

    def test_the_order_line_joins_to_a_hostname_label(self) -> None:
        inputs = load_inputs_module()
        name = re.compile(interface()["properties"]["name"]["pattern"])
        sales_order, line = inputs.order_line(
            {"SALES_ORDER": "S" + "o" * 55, "LINE": "999999"}, interface()
        )
        joined = f"{sales_order}-{line}"
        self.assertEqual(len(joined), 63)
        self.assertTrue(name.fullmatch(joined))

    def test_negative_control_a_57_character_sales_order_is_refused(self) -> None:
        inputs = load_inputs_module()
        with self.assertRaisesRegex(inputs.RefusedError, "^SALES_ORDER"):
            inputs.order_line({"SALES_ORDER": "S" * 57, "LINE": "999999"}, interface())
        self.assertIsNone(
            re.fullmatch(
                interface()["properties"]["name"]["pattern"], "S" * 57 + "-999999"
            )
        )

    def test_negative_control_a_leading_digit_is_refused(self) -> None:
        inputs = load_inputs_module()
        with self.assertRaisesRegex(inputs.RefusedError, "^SALES_ORDER"):
            inputs.order_line({"SALES_ORDER": "1SO", "LINE": "1"}, interface())
        with self.assertRaisesRegex(inputs.RefusedError, "^LINE"):
            inputs.order_line({"SALES_ORDER": "SO", "LINE": "1-2"}, interface())

    def test_negative_control_a_leading_zero_line_is_refused(self) -> None:
        inputs = load_inputs_module()
        self.assertEqual(
            inputs.order_line({"SALES_ORDER": "SO", "LINE": "7"}, interface()),
            ("SO", "7"),
        )
        for line in ("007", "0"):
            with (
                self.subTest(line=line),
                self.assertRaisesRegex(inputs.RefusedError, "^LINE"),
            ):
                inputs.order_line({"SALES_ORDER": "SO", "LINE": line}, interface())


if __name__ == "__main__":
    unittest.main()
