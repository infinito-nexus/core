from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
import tomllib
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import read_text

from ._render import DOCKERFILE, PROXMOX, ROLE, render

LAUNCHER = read_text(str(ROLE / "files" / "shell" / "proxmox-launcher.sh"))
ANSWER = read_text(str(ROLE / "files" / "image" / "answer.toml"))
FIRST_BOOT = read_text(str(ROLE / "files" / "shell" / "first-boot.sh"))
PLACEHOLDER = "@ROOT_PASSWORD_HASHED@"
FAKE_HASH = "$6$fakesalt$fakehash"
RESERVED = "example.invalid"
ISO_BYTES = b"proxmox installer iso\n"

_FAKES = {
    "curl": 'out=""; while [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done; cp "$FAKE_ISO" "$out"\n',
    "proxmox-auto-install-assistant": 'printf "%s\\n" "$*" >> "$FAKE_LOG"; [ "$1" = "validate-answer" ] && cp "$2" "$FAKE_ANSWER"; [ "$1" = prepare-iso ] && : > "$FAKE_DIR/prepared"; exit 0\n',
    "openssl": f"cat >/dev/null; printf '%s\\n' '{FAKE_HASH}'\n",
    "qemu-img": 'printf "qemu-img %s\\n" "$*" >> "$FAKE_LOG"; case "$1" in create) : > "$5";; info) printf \'{"actual-size": 4294967296}\\n\';; esac\n',
    "qemu-system-x86_64": 'printf "qemu %s\\n" "$*" >> "$FAKE_LOG"\n',
}


@dataclass
class Build:
    """Args:
    returncode: exit status of the launcher.
    stderr: what it died with.
    log: every call of a faked tool, one per line.
    answer: the answer file the assistant validated, "" when it never ran.
    base: the base disks the build kept.
    """

    returncode: int
    stderr: str
    log: str
    answer: str
    base: list[str]


def _share(root: Path, pin: str, answer: str = ANSWER) -> Path:
    share = root / "share"
    share.mkdir()
    (share / "iso.sha256").write_text(f"{pin}\n", encoding="utf-8")
    (share / "answer.toml").write_text(answer, encoding="utf-8")
    (share / "first-boot.sh").write_text(FIRST_BOOT, encoding="utf-8")
    return share


def _tools(root: Path) -> Path:
    tools = root / "bin"
    tools.mkdir()
    for name, body in _FAKES.items():
        tool = tools / name
        tool.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tools


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text()  # nocheck: cache-read tempdir fixture


def run_build(script: str, iso: bytes, pin: str) -> Build:
    """Args:
        script: launcher script text.
        iso: bytes the faked download delivers.
        pin: SHA-256 the image pins.

    Returns:
        The outcome of ``build`` with every external tool faked.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        share = _share(root, pin)
        tools = _tools(root)
        (root / "installer.iso").write_bytes(iso)
        (root / "base").mkdir()
        (root / "launcher.sh").write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["sh", str(root / "launcher.sh"), "build"],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{tools}:{os.environ['PATH']}",
                "PROXMOX_LAUNCHER_SHARE": str(share),
                "PROXMOX_GUEST_BASE_DIR": str(root / "base"),
                "PROXMOX_ISO_URL": "https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1.iso",
                "PROXMOX_GUEST_CPUS": "2",
                "PROXMOX_GUEST_MEMORY": "4g",
                "PROXMOX_GUEST_DISK": "64G",
                "FAKE_ISO": str(root / "installer.iso"),
                "FAKE_LOG": str(root / "log"),
                "FAKE_ANSWER": str(root / "validated.toml"),
                "FAKE_DIR": str(root),
            },
        )
        return Build(
            result.returncode,
            result.stderr,
            _read(root / "log"),
            _read(root / "validated.toml"),
            sorted(path.name for path in (root / "base").glob("base-*.qcow2")),
        )


def answer_findings(text: str) -> list[str]:
    """Args:
        text: an answer file.

    Returns:
        Every value in it that belongs to a deployment or breaks the unattended build.
    """
    findings = []
    if "{{" in text or "{%" in text:
        findings.append("templated value")
    answer = tomllib.loads(text)
    general = answer["global"]
    if general.get("reboot-mode") != "power-off":
        findings.append(f"reboot-mode {general.get('reboot-mode')!r}")
    if general.get("root-password-hashed") != PLACEHOLDER:
        findings.append("root-password-hashed is no build placeholder")
    if "root-password" in general:
        findings.append("plain root-password")
    for key in ("fqdn", "mailto"):
        domain = str(general.get(key, "")).rsplit("@", 1)[-1]
        if domain != RESERVED and not domain.endswith(f".{RESERVED}"):
            findings.append(f"{key} {general.get(key)!r} outside {RESERVED}")
    if answer.get("first-boot", {}).get("source") != "from-iso":
        findings.append("no first-boot hook from the ISO")
    return findings


class TestImageBuild(unittest.TestCase):
    PIN = hashlib.sha256(ISO_BYTES).hexdigest()

    def test_the_image_build_verifies_the_iso(self):
        good = run_build(LAUNCHER, ISO_BYTES, self.PIN)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(len(good.base), 1)
        self.assertIn("prepare-iso", good.log)
        self.assertIn("--fetch-from iso", good.log)
        self.assertIn("--on-first-boot", good.log)
        bad = run_build(LAUNCHER, ISO_BYTES + b"tampered", self.PIN)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("SHA-256", bad.stderr)
        self.assertNotIn("prepare-iso", bad.log)
        self.assertNotIn("qemu ", bad.log)
        self.assertEqual(bad.base, [])

    def test_negative_control_a_build_without_the_check_takes_a_tampered_iso(self):
        mutant = LAUNCHER.replace('\tverify_iso "$work/installer.iso"\n', "", 1)
        self.assertNotEqual(mutant, LAUNCHER)
        bad = run_build(mutant, ISO_BYTES + b"tampered", self.PIN)
        self.assertIn("prepare-iso", bad.log)

    def test_the_pin_reaches_the_image(self):
        dockerfile = render(DOCKERFILE, "vm")
        self.assertIn(
            'printf \'%s\\n\' "${PROXMOX_ISO_SHA256}" > "${PROXMOX_LAUNCHER_SHARE}/iso.sha256"',
            dockerfile,
        )
        self.assertIn('test -n "${PROXMOX_ISO_SHA256}"', dockerfile)
        self.assertRegex(PROXMOX["ve"]["iso"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            PROXMOX["ve"]["iso"]["file"], r"^proxmox-ve_\d+\.\d+-\d+\.iso$"
        )

    def test_the_answer_file_holds_no_deploy_value(self):
        self.assertEqual(answer_findings(ANSWER), [])
        build = run_build(LAUNCHER, ISO_BYTES, self.PIN)
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertNotIn(PLACEHOLDER, build.answer)
        self.assertIn(f'root-password-hashed = "{FAKE_HASH}"', build.answer)
        self.assertEqual(
            set(build.answer.splitlines()) - set(ANSWER.splitlines()),
            {f'root-password-hashed = "{FAKE_HASH}"'},
        )

    def test_negative_control_a_deploy_value_in_the_answer_file_is_caught(self):
        for old, new in (
            ('reboot-mode = "power-off"', 'reboot-mode = "reboot"'),
            (f'"{PLACEHOLDER}"', '"$6$real$hash"'),
            ('fqdn = "pve.example.invalid"', 'fqdn = "pve.{{ DOMAIN_PRIMARY }}"'),
            ('mailto = "root@example.invalid"', 'mailto = "admin@example.org"'),
        ):
            mutant = ANSWER.replace(old, new)
            self.assertNotEqual(mutant, ANSWER, old)
            self.assertNotEqual(answer_findings(mutant), [], new)

    def test_the_image_tag_follows_the_pin_the_answer_file_and_the_hook(self):
        tags = set()
        for pin, answer in (
            (self.PIN, ANSWER),
            ("0" * 64, ANSWER),
            (self.PIN, ANSWER + "\n"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                share = _share(Path(tmp), pin, answer)
                result = subprocess.run(
                    ["sh", "-c", LAUNCHER, "proxmox-launcher", "tag"],
                    capture_output=True,
                    text=True,
                    check=True,
                    env={
                        "PATH": os.environ["PATH"],
                        "PROXMOX_LAUNCHER_SHARE": str(share),
                    },
                )
                tags.add(result.stdout.strip())
        self.assertEqual(len(tags), 3)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", tag) for tag in tags))


if __name__ == "__main__":
    unittest.main()
