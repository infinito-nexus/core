from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from ._render import PROXMOX, ROLE

SCRIPT = read_text(str(ROLE / "files" / "shell" / "templates.sh"))
TASK = load_yaml_any(str(ROLE / "tasks" / "02_templates.yml"), default_if_missing=[])[0]
IMAGE = b"debian cloud image\n"
PIN = hashlib.sha256(IMAGE).hexdigest()
TEMPLATES = PROXMOX["workspaces"]["templates"]

_FAKES = {
    "curl": 'out=""; while [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done; cp "$FAKE_IMAGE" "$out"\n',
    "qm": (
        'printf "qm %s\\n" "$*" >> "$FAKE_LOG"\n'
        'if [ "$1" = config ] && [ -f "$FAKE_CONFIGS/$2" ]; then cat "$FAKE_CONFIGS/$2"; exit 0; fi\n'
        '[ "$1" = config ] && exit 2\n'
        "exit 0\n"
    ),
}


@dataclass
class Run:
    """Args:
    returncode: exit status of the script.
    stdout: its [CHANGED] lines.
    stderr: what it died with.
    calls: every qm call, one per line.
    """

    returncode: int
    stdout: str
    stderr: str
    calls: list[str]


def run_templates(
    script: str, image: bytes, configs: dict[int, str] | None = None
) -> Run:
    """Args:
        script: the template script text.
        image: bytes the faked download delivers.
        configs: ``qm config`` output per existing VM id.

    Returns:
        The outcome with ``qm`` and ``curl`` faked.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tools = root / "bin"
        tools.mkdir()
        for name, body in _FAKES.items():
            tool = tools / name
            tool.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        (root / "configs").mkdir()
        for vmid, text in (configs or {}).items():
            (root / "configs" / str(vmid)).write_text(text, encoding="utf-8")
        (root / "image").write_bytes(image)
        result = subprocess.run(
            ["sh", "-s"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{tools}:{os.environ['PATH']}",
                "PROXMOX_STORAGE": PROXMOX["workspaces"]["storage"],
                "PROXMOX_BRIDGE": PROXMOX["workspaces"]["bridge"],
                "PROXMOX_IMAGE_URL": PROXMOX["workspaces"]["image"]["url"],
                "PROXMOX_IMAGE_SHA256": PIN,
                "PROXMOX_TEMPLATE_KVM": str(TEMPLATES["kvm"]),
                "PROXMOX_TEMPLATE_EMULATED": str(TEMPLATES["emulated"]),
                "FAKE_IMAGE": str(root / "image"),
                "FAKE_LOG": str(root / "log"),
                "FAKE_CONFIGS": str(root / "configs"),
            },
        )
        calls = _logged(root / "log")
    return Run(result.returncode, result.stdout, result.stderr, calls)


def _logged(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()  # nocheck: cache-read tempdir fixture


def _create(run: Run, vmid: int) -> str:
    return next(call for call in run.calls if call.startswith(f"qm create {vmid} "))


def template_findings(run: Run) -> list[str]:
    """Args:
        run: a run that built both templates.

    Returns:
        Every way a template departs from 116 decision 1.
    """
    findings = []
    try:
        kvm, emulated = (
            _create(run, TEMPLATES["kvm"]),
            _create(run, TEMPLATES["emulated"]),
        )
    except StopIteration:
        return ["a template was not created"]
    if "--kvm 1 " not in kvm:
        findings.append("the kvm template does not set kvm 1")
    if "--kvm 0 " not in emulated:
        findings.append("the emulated template does not set kvm 0")
    if "--cpu qemu64 " not in emulated:
        findings.append("the emulated template does not set cpu qemu64")
    for vmid in TEMPLATES.values():
        if f"qm template {vmid}" not in run.calls:
            findings.append(f"{vmid} is no template")
        if not any(
            c.startswith(f"qm set {vmid} --ide2 ") and ":cloudinit" in c
            for c in run.calls
        ):
            findings.append(f"{vmid} has no cloud-init drive")
    return findings


class TestTemplates(unittest.TestCase):
    def test_the_templates_are_built_as_pinned(self):
        run = run_templates(SCRIPT, IMAGE)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(template_findings(run), [])
        self.assertEqual(run.stdout.count("[CHANGED]"), 2)
        imports = [c for c in run.calls if "import-from=" in c]
        self.assertEqual(len(imports), 2)
        self.assertTrue(
            all(f"{PROXMOX['workspaces']['storage']}:0," in c for c in imports)
        )
        bad = run_templates(SCRIPT, IMAGE + b"tampered")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("SHA-256", bad.stderr)
        self.assertFalse(any("import-from=" in c for c in bad.calls))

    def test_negative_control_a_dropped_kvm_0_fails(self):
        mutant = SCRIPT.replace(
            "workspace-emulated 0 qemu64", "workspace-emulated 1 qemu64"
        )
        self.assertNotEqual(mutant, SCRIPT)
        self.assertTrue(
            any("kvm 0" in f for f in template_findings(run_templates(mutant, IMAGE)))
        )

    def test_negative_control_a_dropped_sum_check_fails(self):
        mutant = SCRIPT.replace(
            '\t[ "$actual" = "$PROXMOX_IMAGE_SHA256" ] || fail',
            "\ttrue || fail",
        )
        self.assertNotEqual(mutant, SCRIPT)
        bad = run_templates(mutant, IMAGE + b"tampered")
        self.assertTrue(any("import-from=" in c for c in bad.calls))

    def test_a_second_deploy_changes_neither_template(self):
        current = f"template: 1\ndescription: image-sha256={PIN}\n"
        run = run_templates(SCRIPT, IMAGE, dict.fromkeys(TEMPLATES.values(), current))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("[CHANGED]", run.stdout)
        self.assertFalse(
            any(c.startswith(("qm create", "qm destroy", "qm set")) for c in run.calls)
        )

    def test_a_new_image_digest_replaces_the_template(self):
        stale = "template: 1\ndescription: image-sha256=" + "0" * 64 + "\n"
        run = run_templates(SCRIPT, IMAGE, {TEMPLATES["kvm"]: stale})
        self.assertIn(f"qm destroy {TEMPLATES['kvm']} --purge 1", run.calls)
        self.assertEqual(template_findings(run), [])

    def test_the_task_runs_the_script_where_pveum_runs(self):
        cmd = TASK["ansible.builtin.shell"]["cmd"]
        self.assertIn("(PROXMOX_GUEST_EXEC + ['sh', '-s'])", cmd)
        self.assertEqual(
            TASK["ansible.builtin.shell"]["stdin"],
            "{{ lookup('file', 'shell/templates.sh') }}",
        )
        self.assertEqual(
            TASK["environment"]["PROXMOX_IMAGE_SHA256"],
            "{{ PROXMOX_WORKSPACES.image.sha256 }}",
        )
        self.assertRegex(PROXMOX["workspaces"]["image"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(TEMPLATES, {"kvm": 9000, "emulated": 9001})


if __name__ == "__main__":
    unittest.main()
