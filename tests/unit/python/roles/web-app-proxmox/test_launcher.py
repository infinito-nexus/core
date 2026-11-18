from __future__ import annotations

import importlib.util
import ipaddress
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.utils.ansible_assert import assert_task, holds, message
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from ._render import (
    COMPOSE,
    KVM_GID,
    LAUNCHER_ID,
    PROXMOX,
    PUBLISHED,
    ROLE,
    planted,
    service,
)

_SPEC = importlib.util.spec_from_file_location(
    "proxmox_flavor_filters", ROLE / "filter_plugins" / "proxmox_flavors.py"
)
_FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FILTERS)
proxmox_nested = _FILTERS.proxmox_nested

GUARD = ROLE / "tasks" / "utils" / "stack" / "guard.yml"
STAGE = load_yaml_any(
    str(ROLE / "tasks" / "utils" / "stack" / "stage.yml"), default_if_missing=[]
)
VM_TASKS = load_yaml_any(
    str(ROLE / "tasks" / "flavors" / "vm.yml"), default_if_missing=[]
)
CONTAINER_TASKS = load_yaml_any(
    str(ROLE / "tasks" / "flavors" / "container.yml"), default_if_missing=[]
)
PROVISION = load_yaml_any(
    str(ROLE / "tasks" / "03_provision.yml"), default_if_missing=[]
)
TEMPLATES = load_yaml_any(
    str(ROLE / "tasks" / "02_templates.yml"), default_if_missing=[]
)
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
LAUNCHER = read_text(str(ROLE / "files" / "shell" / "proxmox-launcher.sh"))
GUEST = read_text(str(ROLE / "files" / "shell" / "pve-guest.sh"))
KVM = ROLE.parent / "svc-virt-kata" / "tasks" / "utils" / "assert" / "kvm.yml"
COHOST = assert_task(
    GUARD,
    "🛑 Refuse a container flavor host shared with identity, gateway or vault",
)
HOST_GRANTS = ("/dev/net/tun", "/dev/vhost-net", "/dev/fuse")
HOST_CAPABILITIES = ("NET_ADMIN", "SYS_ADMIN")
GUEST_HOSTFWD = re.compile(r"hostfwd=tcp:([^:]+):\$PROXMOX_GUEST_(\w+)_PORT-:(\d+)")
FIRST_BOOT = read_text(str(ROLE / "files" / "shell" / "first-boot.sh"))
POOLS_SPEC = read_text(str(ROLE / "files" / "playwright" / "test-workspace-pools.js"))
SHELL_FUNCTION = re.compile(r"^\w+\(\) \{\n.*?^\}\n", re.MULTILINE | re.DOTALL)
RECORD_PATH = re.compile(r"^RECORD=(\S+)$", re.MULTILINE)
SPEC_FORMATS = dict(
    re.findall(
        r"^  (\w+): /(.+)/,$",
        POOLS_SPEC.split("const FIRST_BOOT_FORMATS = {", 1)[-1].split("};", 1)[0],
        re.MULTILINE,
    )
)
MACHINE_ID = "0123456789abcdef0123456789abcdef"
ROOT_HASH = "$6$fakesalt$fakehash"
GUEST_FILES = {
    "etc/ssh/ssh_host_ed25519_key": "PRIVATE ED25519 HOST KEY\n",
    "etc/ssh/ssh_host_ed25519_key.pub": "ssh-ed25519 AAAAC3image root@pve\n",
    "etc/ssh/ssh_host_rsa_key": "PRIVATE RSA HOST KEY\n",
    "etc/ssh/ssh_host_rsa_key.pub": "ssh-rsa AAAAB3image root@pve\n",
    "etc/machine-id": f"{MACHINE_ID}\n",
    "etc/shadow": f"root:{ROOT_HASH}:19000:0:99999:7:::\n",
    "etc/pve/local/pve-ssl.pem": "NODE CERTIFICATE\n",
    "etc/pve/local/pve-ssl.key": "PRIVATE NODE KEY\n",
    "etc/pve/pve-root-ca.pem": "CLUSTER CA\n",
    "etc/pve/priv/pve-root-ca.key": "PRIVATE CLUSTER CA KEY\n",
}
GUEST_SECRETS = {
    "a private key": "PRIVATE",
    "the machine id": MACHINE_ID,
    "the root password hash": ROOT_HASH,
}
_GUEST_FAKES = {
    "ssh-keygen": (
        "kind=${2##*ssh_host_}; kind=${kind%_key.pub}; "
        "printf '256 SHA256:%s root@pve (%s)\\n' "
        '"$(sha256sum <"$2" | cut -c1-43)" '
        '"$(printf %s "$kind" | tr "[:lower:]" "[:upper:]")"\n'
    ),
    "openssl": (
        '[ -r "$6" ] || exit 1; '
        "printf 'sha256 Fingerprint=%s\\n' "
        '"$(sha256sum <"$6" | cut -c1-64 | tr a-f A-F | sed \'s/../&:/g; s/:$//\')"\n'
    ),
    "getent": 'grep "^$2:" "$FAKE_ROOT/etc/shadow"\n',
}
IMAGE_MEASURE = 'image_digests="$(measure image)"'
DEPLOYED_MEASURE = "\tmeasure deployed\n"
ADMIT_LAUNCHER = ">>/root/.ssh/authorized_keys"
REGENERATION_STEPS = (
    "rm -f /etc/ssh/ssh_host_*",
    "rm -f /etc/machine-id",
    "pvecm updatecerts --force",
    'usermod -p "$root_hash" root',
)


def launcher_findings(rendered: dict) -> list[str]:
    """Args:
        rendered: the rendered ``proxmox`` compose service of the vm flavor.

    Returns:
        Every way the service is more privileged than the launcher may be.
    """
    findings = []
    user = str(rendered.get("user", ""))
    uid = user.split(":", maxsplit=1)[0]
    if not uid.isdigit() or int(uid) == 0:
        findings.append(f"user {user!r} is no non-root UID")
    if rendered.get("devices") != ["/dev/kvm"]:
        findings.append(f"devices {rendered.get('devices')} are not /dev/kvm alone")
    if rendered.get("cap_add"):
        findings.append(f"cap_add {rendered['cap_add']}")
    if rendered.get("cap_drop") != ["ALL"]:
        findings.append(f"cap_drop {rendered.get('cap_drop')} keeps capabilities")
    if "no-new-privileges:true" not in (rendered.get("security_opt") or []):
        findings.append("no-new-privileges is not set")
    findings.extend(
        f"{key} is set"
        for key in ("privileged", "cgroup", "pid", "ipc", "network_mode", "userns_mode")
        if key in rendered
    )
    text = repr(rendered)
    findings.extend(
        f"{grant} is granted"
        for grant in (*HOST_GRANTS, *HOST_CAPABILITIES)
        if grant in text
    )
    return findings


def _assert_planted(test: unittest.TestCase, old: str, new: str, needle: str) -> None:
    findings = launcher_findings(service("vm", planted(COMPOSE, old, new)))
    test.assertTrue(any(needle in finding for finding in findings), findings)


def measured(hook: str, files: dict[str, str]) -> dict[str, str]:
    """Args:
        hook: text of the first-boot hook.
        files: guest files by path below ``/``, planted into a scratch root.

    Returns:
        The ``image.<item>`` lines the hook's ``measure`` writes for that guest, by key.
    """
    functions = "".join(SHELL_FUNCTION.findall(hook)).replace(
        "/etc/", "$FAKE_ROOT/etc/"
    )
    with tempfile.TemporaryDirectory() as tmp:
        guest = Path(tmp) / "guest"
        for name, content in files.items():
            path = guest / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        tools = Path(tmp) / "bin"
        tools.mkdir()
        for name, body in _GUEST_FAKES.items():
            tool = tools / name
            tool.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        result = subprocess.run(
            ["sh", "-c", f"set -eu\n{functions}measure image\n"],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": f"{tools}:{os.environ['PATH']}", "FAKE_ROOT": str(guest)},
        )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def record_findings(record: dict[str, str]) -> list[str]:
    """Args:
        record: first-boot record lines by key.

    Returns:
        Every key the spec does not expect, every value its format refuses, and every secret it carries.
    """
    findings = []
    expected = {f"image.{item}" for item in SPEC_FORMATS}
    if set(record) != expected:
        findings.append(f"keys {sorted(record)} are not {sorted(expected)}")
    for key, value in sorted(record.items()):
        item = key.split(".", 1)[-1]
        if item in SPEC_FORMATS and not re.fullmatch(SPEC_FORMATS[item], value):
            findings.append(f"{key} {value!r} is malformed")
        findings.extend(
            f"{key} carries {name}"
            for name, secret in GUEST_SECRETS.items()
            if secret in value
        )
    return findings


def order_findings(hook: str) -> list[str]:
    """Args:
        hook: text of the first-boot hook.

    Returns:
        Every regeneration step the image measurement does not precede or the deployed one does not follow, and a launcher key admitted before the record exists.
    """
    image, deployed, admit = (
        hook.find(IMAGE_MEASURE),
        hook.find(DEPLOYED_MEASURE),
        hook.find(ADMIT_LAUNCHER),
    )
    if min(image, deployed, admit) < 0:
        return ["the hook measures no image, no deployment or admits no launcher key"]
    findings = []
    for step in REGENERATION_STEPS:
        at = hook.find(step)
        if not image < at < deployed:
            findings.append(f"{step!r} is not between both measurements")
    if not deployed < admit:
        findings.append("the launcher key is admitted before the record is written")
    if (
        "\tprintf '%s\\n' \"$image_digests\"\n" not in hook
        or '} >"$RECORD"' not in hook
    ):
        findings.append("the record does not hold the image measurement")
    return findings


class TestLauncherCompose(unittest.TestCase):
    def test_the_launcher_compose_is_unprivileged(self):
        rendered = service("vm")
        self.assertEqual(launcher_findings(rendered), [])
        self.assertEqual(rendered["user"], f"{LAUNCHER_ID}:{LAUNCHER_ID}")
        self.assertEqual(rendered["group_add"], [str(KVM_GID)])
        self.assertEqual(rendered["ports"], [PUBLISHED.strip('"')])

    def test_negative_control_a_root_user_is_caught(self):
        _assert_planted(
            self,
            'user: "{{ PROXMOX_LAUNCHER_ID }}:{{ PROXMOX_LAUNCHER_ID }}"',
            'user: "0:0"',
            "non-root",
        )

    def test_negative_control_a_second_device_is_caught(self):
        _assert_planted(
            self,
            "    devices:\n      - /dev/kvm\n    cap_drop:",
            "    devices:\n      - /dev/kvm\n      - /dev/net/tun\n    cap_drop:",
            "devices",
        )

    def test_negative_control_an_added_capability_is_caught(self):
        _assert_planted(
            self,
            "    cap_drop:\n      - ALL\n",
            "    cap_drop:\n      - ALL\n    cap_add:\n      - NET_ADMIN\n",
            "cap_add",
        )

    def test_negative_control_kept_capabilities_are_caught(self):
        _assert_planted(self, "    cap_drop:\n      - ALL\n", "", "cap_drop")

    def test_negative_control_a_missing_no_new_privileges_is_caught(self):
        _assert_planted(
            self,
            "    security_opt:\n      - no-new-privileges:true\n",
            "",
            "no-new-privileges",
        )

    def test_negative_control_a_private_cgroup_is_caught(self):
        _assert_planted(
            self,
            "    stop_grace_period: 3m\n",
            "    stop_grace_period: 3m\n    cgroup: private\n",
            "cgroup",
        )

    def test_negative_control_a_host_grant_is_caught(self):
        for grant in HOST_GRANTS:
            _assert_planted(
                self,
                "      - /dev/kvm\n    cap_drop:",
                f"      - /dev/kvm\n      - {grant}\n    cap_drop:",
                grant,
            )
        for capability in HOST_CAPABILITIES:
            _assert_planted(
                self,
                "    cap_drop:\n      - ALL\n",
                f"    cap_drop:\n      - ALL\n    cap_add:\n      - {capability}\n",
                capability,
            )


class TestBesideTheIdentityRoles(unittest.TestCase):
    def test_the_vm_flavor_runs_beside_the_identity_roles(self):
        peers = ["web-app-keycloak", "web-app-openbao"]
        self.assertTrue(
            holds(COHOST, {"PROXMOX_FLAVOR": "vm", "PROXMOX_COHOSTED_PEERS": peers})
        )
        self.assertFalse(
            holds(
                COHOST,
                {"PROXMOX_FLAVOR": "container", "PROXMOX_COHOSTED_PEERS": peers},
            )
        )

    def test_the_vm_flavor_renders_none_of_the_host_grants(self):
        text = repr(service("vm"))
        for grant in (*HOST_GRANTS, *HOST_CAPABILITIES, "cgroup"):
            self.assertNotIn(grant, text)


class TestGuestChannel(unittest.TestCase):
    def test_the_guest_channel_stays_inside_the_container(self):
        forwards = {
            port: (address, guest)
            for address, port, guest in GUEST_HOSTFWD.findall(LAUNCHER)
        }
        self.assertEqual(forwards["SSH"], ("127.0.0.1", "22"))
        api_address, api_port = forwards["API"]
        self.assertTrue(ipaddress.ip_address(api_address).is_unspecified)
        self.assertEqual(api_port, "8006")
        rendered = service("vm")
        self.assertEqual(rendered["ports"], [PUBLISHED.strip('"')])
        self.assertNotIn(str(PROXMOX["guest"]["ssh_port"]), repr(rendered["ports"]))
        self.assertIn("HostName 127.0.0.1", LAUNCHER)
        self.assertIn("StrictHostKeyChecking yes", LAUNCHER)
        self.assertIn('exec ssh -F "$PROXMOX_GUEST_DIR/ssh/config" guest "$@"', GUEST)
        self.assertNotIn("ssh_port", read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE)))

    def test_negative_control_a_forward_on_every_address_is_caught(self):
        mutant = LAUNCHER.replace(
            "hostfwd=tcp:127.0.0.1:$PROXMOX_GUEST_SSH_PORT-:22",
            "hostfwd=tcp:0.0.0.0:$PROXMOX_GUEST_SSH_PORT-:22",
        )
        self.assertNotEqual(mutant, LAUNCHER)
        forwards = {port: address for address, port, _ in GUEST_HOSTFWD.findall(mutant)}
        self.assertNotEqual(forwards["SSH"], "127.0.0.1")


class TestNestedMode(unittest.TestCase):
    def test_the_guest_mode_follows_the_host_nested_flag(self):
        for parameters, nested in (
            ("Y\n", True),
            ("1\n", True),
            ("N\n", False),
            ("0\n", False),
            ("", False),
            ("N\nY\n", True),
        ):
            self.assertIs(proxmox_nested(parameters), nested, repr(parameters))
        mode = next(
            t
            for t in VM_TASKS
            if "PROXMOX_VM_KVM" in str(t.get("ansible.builtin.set_fact"))
        )
        self.assertEqual(
            mode["ansible.builtin.set_fact"]["PROXMOX_VM_KVM"],
            "{{ proxmox_nested_parameter.stdout | proxmox_nested }}",
        )
        read = next(
            t for t in VM_TASKS if t.get("register") == "proxmox_nested_parameter"
        )
        self.assertIn(
            "/sys/module/kvm_intel/parameters/nested",
            read["ansible.builtin.command"]["argv"],
        )
        self.assertIn(
            "/sys/module/kvm_amd/parameters/nested",
            read["ansible.builtin.command"]["argv"],
        )
        self.assertEqual(read["delegate_to"], "{{ PROXMOX_HOST_NODE }}")
        container = next(
            t
            for t in CONTAINER_TASKS
            if "PROXMOX_VM_KVM" in str(t.get("ansible.builtin.set_fact"))
        )
        self.assertIs(container["ansible.builtin.set_fact"]["PROXMOX_VM_KVM"], True)
        record = next(
            t
            for t in PROVISION
            if "kv.yml" in str(t.get("ansible.builtin.include_tasks"))
        )
        self.assertEqual(
            record["vars"]["openbao_kv_data"]["kvm"], "{{ PROXMOX_VM_KVM | bool }}"
        )
        self.assertEqual(
            record["vars"]["openbao_kv_path"], "{{ PROXMOX_PROVISION_PATH }}"
        )
        self.assertEqual(
            VARS["PROXMOX_PROVISION_PATH"], "provision/proxmox-{{ inventory_hostname }}"
        )
        self.assertEqual(VARS["PROXMOX_PROVISION_MOUNT"], "platform")
        log = next(t for t in TEMPLATES if "ansible.builtin.debug" in t)
        self.assertIn("PROXMOX_VM_KVM", log["ansible.builtin.debug"]["msg"])

    def test_negative_control_an_ignored_nested_flag_is_caught(self):
        self.assertNotEqual(proxmox_nested("N\n"), proxmox_nested("Y\n"))


class TestFirstBootRecord(unittest.TestCase):
    def test_the_record_holds_the_spec_formats_and_no_secret(self):
        self.assertEqual(
            sorted(SPEC_FORMATS),
            ["machine_id", "node_certificate", "root_ca", "root_hash", "ssh_host_keys"],
        )
        record = measured(FIRST_BOOT, GUEST_FILES)
        self.assertEqual(record_findings(record), [])
        self.assertRegex(
            record["image.ssh_host_keys"], r"^ED25519:SHA256:\S+,RSA:SHA256:\S+$"
        )

    def test_negative_control_a_raw_root_hash_in_the_record_is_caught(self):
        mutant = FIRST_BOOT.replace(
            '"$(digest "$(getent shadow root | cut -d: -f2)")"',
            '"$(getent shadow root | cut -d: -f2)"',
        )
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertIn(
            "image.root_hash carries the root password hash",
            record_findings(measured(mutant, GUEST_FILES)),
        )

    def test_a_missing_value_stays_empty_and_fails_the_spec_format(self):
        missing = {"etc/machine-id", "etc/pve/local/pve-ssl.pem"}
        guest = {k: v for k, v in GUEST_FILES.items() if k not in missing}
        record = measured(FIRST_BOOT, guest)
        self.assertEqual(record["image.machine_id"], "")
        self.assertEqual(record["image.node_certificate"], "")
        self.assertEqual(
            record_findings(record),
            [
                "image.machine_id '' is malformed",
                "image.node_certificate '' is malformed",
            ],
        )

    def test_negative_control_a_digest_of_nothing_passes_the_spec_format(self):
        mutant = FIRST_BOOT.replace('[ -z "$1" ] || printf', "printf")
        self.assertNotEqual(mutant, FIRST_BOOT)
        guest = {k: v for k, v in GUEST_FILES.items() if k != "etc/machine-id"}
        value = measured(mutant, guest)["image.machine_id"]
        self.assertNotEqual(value, "")
        self.assertRegex(value, SPEC_FORMATS["machine_id"])

    def test_the_hook_measures_the_image_first_and_admits_the_launcher_last(self):
        self.assertEqual(order_findings(FIRST_BOOT), [])

    def test_negative_control_a_late_image_measurement_is_caught(self):
        mutant = FIRST_BOOT.replace(f"{IMAGE_MEASURE}\n\n", "", 1).replace(
            "pvecm updatecerts --force\n",
            f"pvecm updatecerts --force\n{IMAGE_MEASURE}\n",
            1,
        )
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertIn(
            "'rm -f /etc/ssh/ssh_host_*' is not between both measurements",
            order_findings(mutant),
        )

    def test_negative_control_an_early_launcher_key_is_caught(self):
        admit = "printf '%s\\n' \"$authorized_key\" >>/root/.ssh/authorized_keys\n"
        mutant = FIRST_BOOT.replace(admit, "").replace(
            f"{IMAGE_MEASURE}\n", f"{IMAGE_MEASURE}\n{admit}", 1
        )
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertIn(
            "the launcher key is admitted before the record is written",
            order_findings(mutant),
        )

    def test_the_role_hands_the_record_to_the_spec(self):
        self.assertEqual(
            RECORD_PATH.search(FIRST_BOOT).group(1),
            VARS["PROXMOX_FIRST_BOOT_DIGESTS_FILE"],
        )
        self.assertEqual(
            set(re.findall(r"printf '%s\.(\w+)=%s\\n'", FIRST_BOOT)), set(SPEC_FORMATS)
        )

    def test_negative_control_a_record_the_role_does_not_read_is_caught(self):
        path = VARS["PROXMOX_FIRST_BOOT_DIGESTS_FILE"]
        mutant = FIRST_BOOT.replace(
            f"RECORD={path}\n", "RECORD=/root/first-boot.digests\n"
        )
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertNotEqual(RECORD_PATH.search(mutant).group(1), path)


class TestCiRow(unittest.TestCase):
    def test_the_role_runs_on_amd64_only(self):
        self.assertEqual(PROXMOX["architectures"], ["amd64"])
        services = read_text(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertRegex(services, r"# nocheck: architecture-pin  Reason: .*/dev/kvm")

    def test_a_missing_kvm_fails_the_row(self):
        include = STAGE[0]
        self.assertIn(
            "svc-virt-kata/tasks/utils/assert/kvm.yml",
            include["ansible.builtin.include_tasks"],
        )
        self.assertEqual(include["vars"]["assert_kvm_consumer"], "{{ application_id }}")
        gid = STAGE[1]["ansible.builtin.set_fact"]["PROXMOX_KVM_GID"]
        self.assertEqual(gid, "{{ assert_kvm_device.stat.gid }}")
        refusal = assert_task(KVM, "🛑 Refuse a host without hardware virtualization")
        facts = {
            "assert_kvm_device": {"stat": {"exists": False, "ischr": False}},
            "assert_kvm_consumer": "web-app-proxmox",
            "inventory_hostname": "runner",
        }
        self.assertFalse(holds(refusal, facts))
        self.assertIn("/dev/kvm", message(refusal, facts))
        self.assertIn("{{ PROXMOX_KVM_GID }}", COMPOSE)


if __name__ == "__main__":
    unittest.main()
