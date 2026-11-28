from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.agents import vm_template

ROLES = PROJECT_ROOT / "roles"
PINS = {"claude-code": ("@anthropic-ai/claude-code", "1.2.3", "ab" * 32)}
TARBALL = f"{vm_template.DOWNLOAD_DIR}/claude-code-1.2.3.tgz"


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.template = self.tmp / "vm-template"
        shutil.copytree(vm_template.TEMPLATE_DIR, self.template)
        self.rootfs = self.template / vm_template.ROOTFS

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, kind: str = "incus", out: str = "out") -> list[list[str]]:
        return vm_template.plan(kind, self.template, ROLES, self.tmp / out)

    def _refused(self, needle: str) -> None:
        with self.assertRaises(vm_template.VmTemplateError) as caught:
            self._plan()
        self.assertIn(needle, str(caught.exception))

    def _spec(self, **fields) -> dict:
        spec = vm_template.load_spec(vm_template.TEMPLATE_DIR)
        spec["tools"]["act"]["sha256"] = "cd" * 32
        spec.update(fields)
        return spec

    def test_ships_the_coding_runtimes(self):
        shipped = vm_template.runtimes(vm_template.TEMPLATE_DIR)
        self.assertEqual(shipped, {"claude-code", "codex", "pi"})
        self.assertNotIn("hermes", shipped)

    def test_one_build_per_vm_kind(self):
        incus = self._plan("incus", "out-incus")
        proxmox = self._plan("proxmox", "out-proxmox")
        for commands in (incus, proxmox):
            self.assertEqual(commands[0][0], "mkosi")
            self.assertTrue(any(arg.endswith(".qcow2") for arg in commands[1]))
        self.assertEqual(len(incus), len(proxmox) + 1)

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(vm_template.VmTemplateError):
            vm_template.plan("vmware", self.template, ROLES, self.tmp / "out")

    def test_template_files_alone_pass(self):
        self._plan()

    def test_rootfs_symlink_out_of_the_template_fails_the_build(self):
        outside = self.tmp / "secret"
        outside.write_text("x", encoding="utf-8")
        (self.rootfs / "leak").symlink_to(outside)
        self._refused("leak")

    def test_rootfs_symlink_inside_the_template_fails_the_build(self):
        (self.rootfs / "loop").symlink_to(self.rootfs / "etc")
        self._refused("a symlink")

    def test_symlinked_rootfs_directory_fails_the_build(self):
        outside = self.tmp / "outside"
        (outside / "root").mkdir(parents=True)
        shutil.rmtree(self.rootfs)
        self.rootfs.symlink_to(outside)
        self._refused("outside the template")

    def test_hard_link_to_a_host_file_fails_the_build(self):
        secret = self.tmp / "netrc"
        secret.write_text("machine x login y password z", encoding="utf-8")
        target = self.rootfs / "root" / ".netrc"
        target.parent.mkdir(parents=True)
        os.link(secret, target)
        self._refused("a hard link")

    def test_fifo_fails_the_build(self):
        os.mkfifo(self.rootfs / "pipe")
        self._refused("not a regular file")

    def test_used_out_directory_fails_the_build(self):
        dropin = self.tmp / "out" / vm_template.PROJECT / "mkosi.conf.d"
        dropin.mkdir(parents=True)
        (dropin / "leak.conf").write_text(
            "[Content]\nExtraTrees=/home/someone/.ssh:/root/.ssh\n", encoding="utf-8"
        )
        self._refused("new, empty --out directory")

    def test_planted_extra_tree_in_out_fails_the_build(self):
        extra = self.tmp / "out" / vm_template.PROJECT / "mkosi.extra" / "root"
        extra.mkdir(parents=True)
        (extra / ".netrc").write_text("planted", encoding="utf-8")
        self._refused("already holds files")

    def test_spec_key_the_build_does_not_read_fails_the_build(self):
        with (self.template / vm_template.SPEC_FILE).open(
            "a", encoding="utf-8"
        ) as spec:
            spec.write("extra_files:\n  - x.txt\n")
        self._refused("keys the build does not read: extra_files")

    def test_runtime_pins_come_from_the_installing_roles(self):
        spec = vm_template.load_spec(vm_template.TEMPLATE_DIR)
        pins = vm_template.runtime_pins(spec, ROLES)
        self.assertEqual(pins["claude-code"][0], "@anthropic-ai/claude-code")
        self.assertTrue(all(version for _, version, _ in pins.values()))

    def test_postinst_runs_in_the_image_and_verifies_every_download(self):
        files = vm_template.mkosi_files(self._spec(), PINS)
        self.assertNotIn("mkosi.postinst", files)
        script = files["mkosi.postinst.chroot"]
        self.assertIn(
            f"{vm_template.NPM_REGISTRY}/@anthropic-ai/claude-code/-/claude-code-1.2.3.tgz",
            script,
        )
        self.assertIn(
            f"echo '{'ab' * 32}  {TARBALL}' | sha256sum --strict -c -", script
        )
        self.assertIn(f"npm install --global --ignore-scripts {TARBALL}", script)
        self.assertTrue(script.rstrip().endswith(f"rm -rf {vm_template.DOWNLOAD_DIR}"))
        self.assertEqual(script.count("sha256sum --strict -c -"), 2)
        self.assertNotIn("| tar", script)

    def test_a_sum_that_is_not_64_lowercase_hex_digits_fails_the_render(self):
        crafted = f"{'ab' * 32}  /etc/hostname\n#"
        digest = "ab" * 32
        for value in (
            "",
            "  ",
            crafted,
            "AB" * 32,
            "ab" * 31,
            digest[:-1],
            digest + "0",
        ):
            pins = {"claude-code": ("@anthropic-ai/claude-code", "1.2.3", value)}
            with self.assertRaises(vm_template.VmTemplateError, msg=repr(value)):
                vm_template.mkosi_files(self._spec(), pins)

    def test_runtime_role_outside_the_roles_directory_is_refused(self):
        outside = self.tmp / "elsewhere" / "meta"
        outside.mkdir(parents=True)
        (outside / "services.yml").write_text(
            "claude:\n  npm_version: 1.0.0\n  update:\n    package: evil\n",
            encoding="utf-8",
        )
        roles = self.tmp / "roles"
        (roles / "nested" / "role").mkdir(parents=True)
        for role in ("../elsewhere", "nested/role", ".", "nested/../.."):
            spec = {"runtimes": {"x": {"role": role, "entity": "claude", "sha256": ""}}}
            with self.assertRaises(vm_template.VmTemplateError, msg=role):
                vm_template.runtime_pins(spec, roles)

    def test_symlinked_spec_is_refused_before_it_is_read(self):
        secret = self.tmp / "outside.yml"
        secret.write_text("db_password_key: hunter2\n", encoding="utf-8")
        spec_file = self.template / vm_template.SPEC_FILE
        spec_file.unlink()
        spec_file.symlink_to(secret)
        with self.assertRaises(vm_template.VmTemplateError) as caught:
            self._plan()
        self.assertIn(f"{spec_file} (outside the template)", str(caught.exception))
        self.assertNotIn("db_password_key", str(caught.exception))

    def test_mkosi_builds_from_the_rootfs_copy_in_the_out_directory(self):
        mkosi = self._plan()[0]
        self.assertIn(f"--extra-tree={self.tmp / 'out' / vm_template.ROOTFS}", mkosi)
        self.assertNotIn(f"--extra-tree={self.rootfs}", mkosi)

    def test_stage_rechecks_the_rootfs_right_before_the_copy(self):
        self._plan()
        victim = self.tmp / "victim"
        victim.write_text("secret", encoding="utf-8")
        os.link(victim, self.rootfs / "late")
        with self.assertRaises(vm_template.VmTemplateError):
            vm_template.stage_rootfs(self.template, self.tmp / "out")
        self.assertFalse((self.tmp / "out" / vm_template.ROOTFS).exists())

    def test_spec_values_are_shell_quoted(self):
        spec = self._spec(version="1'; touch /tmp/pwned; echo '")
        finalize = vm_template.mkosi_files(spec, PINS)["mkosi.finalize"]
        self.assertIn(
            "printf '%s\\n' '1'\"'\"'; touch /tmp/pwned; echo '\"'\"''", finalize
        )

    def test_output_name_matches_the_planned_image(self):
        spec = self._spec()
        conf = vm_template.mkosi_files(spec, PINS)["mkosi.conf"]
        image = f"{vm_template.IMAGE_ID}-{spec['version']}"
        self.assertIn(f"Output={image}\n", conf)
        self.assertIn(f"{image}.raw", " ".join(self._plan()[1]))

    def test_image_is_credential_free_and_versioned(self):
        spec = self._spec()
        files = vm_template.mkosi_files(spec, PINS)
        self.assertIn('/etc/machine-id"', files["mkosi.finalize"])
        self.assertIn("ssh_host_", files["mkosi.finalize"])
        self.assertIn(vm_template.VERSION_FILE, files["mkosi.finalize"])
        self.assertIn(spec["snapshot"], files["mkosi.conf"])
        self.assertNotIn("cloud-init", spec["apt"])
        self.assertNotIn("openssh-server", spec["apt"])
        self.assertIn(
            f'template_version: "{spec["version"]}"', vm_template.incus_metadata(spec)
        )


if __name__ == "__main__":
    unittest.main()
