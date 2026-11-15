from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from . import PROJECT_ROOT

GUARD = PROJECT_ROOT / "roles/web-app-semaphore/files/python/inventory_guard.py"
LIB = PROJECT_ROOT / "roles/web-app-semaphore/files/shell/repository/lib.sh"
BIN = Path(sys.executable).parent
SECRET = "s3cr3t-{{-value"
PLAIN = {
    "_meta": {
        "hostvars": {
            "203.0.113.10": {
                "ansible_user": "admin",
                "users": {"admin": {"authorized_keys": ["ssh-ed25519 AAAA"]}},
                "ports": [22, 443],
                "enabled": True,
            }
        }
    },
    "all": {"children": ["ungrouped"]},
}
EVIL_VARS_PLUGIN = """from pathlib import Path
Path({marker!r}).touch()
from ansible.plugins.vars import BaseVarsPlugin
class VarsModule(BaseVarsPlugin):
    REQUIRES_ENABLED = False
    def get_vars(self, loader, path, entities, cache=True):
        return {{}}
"""


def load():
    """Returns:
    The loaded ``inventory_guard`` module.
    """
    spec = spec_from_file_location("inventory_guard", str(GUARD))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InventoryGuardTests(unittest.TestCase):
    def setUp(self):
        self.mod = load()

    def guarded(self, inventory):
        """Args:
        inventory: the inventory as ``ansible-inventory --list`` prints it.

        Returns:
            ``(exit code, stderr)`` of the guard against the real core tree.
        """
        stderr = io.StringIO()
        code = self.mod.main(io.StringIO(json.dumps(inventory)), stderr, PROJECT_ROOT)
        return code, stderr.getvalue()

    def test_an_inventory_without_jinja_or_core_settings_passes(self):
        self.assertEqual(self.mod.templates(PLAIN), [])
        self.assertEqual(self.guarded(PLAIN), (0, ""))

    def test_a_variable_shadowing_a_core_setting_is_named(self):
        settings = self.mod.core_settings(PROJECT_ROOT)
        self.assertIn("STACK_HOST", settings)
        self.assertIn("MASK_CREDENTIALS_IN_LOGS", settings)
        host = PLAIN["_meta"]["hostvars"]["203.0.113.10"]
        for name, value in (
            ("STACK_HOST", "localhost"),
            ("MASK_CREDENTIALS_IN_LOGS", False),
        ):
            with self.subTest(name):
                inventory = {
                    **PLAIN,
                    "_meta": {"hostvars": {"203.0.113.10": {**host, name: value}}},
                }
                code, stderr = self.guarded(inventory)
                self.assertEqual(code, 1)
                self.assertIn(
                    f"_meta.hostvars.203.0.113.10.{name} shadows a core setting", stderr
                )
        with self.subTest("group vars"):
            code, stderr = self.guarded(
                {
                    **PLAIN,
                    "workspace": {"hosts": [], "vars": {"STACK_HOST": "localhost"}},
                }
            )
            self.assertEqual(code, 1)
            self.assertIn("workspace.vars.STACK_HOST shadows a core setting", stderr)

    def test_the_inventory_settings_pass_although_they_are_core_settings(self):
        settings = self.mod.core_settings(PROJECT_ROOT)
        self.assertLessEqual(self.mod.INVENTORY_SETTINGS, settings)
        host = PLAIN["_meta"]["hostvars"]["203.0.113.10"]
        inventory = {
            "_meta": {
                "hostvars": {
                    "203.0.113.10": {
                        **host,
                        "DOMAIN_PRIMARY": "shop.example.org",
                        "TLS_ENABLED": True,
                    }
                }
            },
            "all": {"children": ["ungrouped"], "vars": {"DEPLOYMENT_MODE": "swarm"}},
        }
        self.assertEqual(self.guarded(inventory), (0, ""))

    def test_every_jinja_marker_is_named_by_its_place_never_by_its_value(self):
        host = PLAIN["_meta"]["hostvars"]["203.0.113.10"]
        cases = {
            "{{": ({**host, "x": "{{ lookup('pipe', 'id') }}"}, "x"),
            "{%": ({**host, "x": "{% if true %}y{% endif %}"}, "x"),
            "{#": ({**host, "x": "{# note #}"}, "x"),
            "nested": (
                {**host, "users": {"admin": {"password": SECRET}}},
                "users.admin.password",
            ),
            "list": ({**host, "ports": [22, "{{ 2 }}"]}, "ports[1]"),
            "key": ({**host, "{{ k }}": 1}, "key '{{ k }}'"),
        }
        for case, (variables, place) in cases.items():
            with self.subTest(case):
                inventory = {
                    **PLAIN,
                    "_meta": {"hostvars": {"203.0.113.10": variables}},
                }
                found = self.mod.templates(inventory)
                self.assertEqual(len(found), 1, found)
                self.assertIn(place, found[0])
                code, stderr = self.guarded(inventory)
                self.assertEqual(code, 1)
                self.assertIn("inventory_guard.py:", stderr)
                self.assertNotIn(SECRET, stderr)

    def test_main_refuses_no_json_and_no_mapping(self):
        for stdin, reason in (
            ("{", "no JSON"),
            ("null", "no mapping"),
            ("[]", "no mapping"),
        ):
            with self.subTest(stdin=stdin):
                stderr = io.StringIO()
                self.assertEqual(
                    self.mod.main(io.StringIO(stdin), stderr, PROJECT_ROOT), 1
                )
                self.assertIn(reason, stderr.getvalue())


class GuardWorkspaceInventoryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.inventory = self.checkout / "devices.yml"
        self.marker = self.root / "ran-on-the-runner"
        self.env = {
            "PATH": f"{BIN}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            "INFINITO_SRC_DIR": str(PROJECT_ROOT),
        }

    def guard(self, src=PROJECT_ROOT):
        """Args:
        src: the core tree the guard takes as ``INFINITO_SRC_DIR``.

        Returns:
            The completed process of the guard.
        """
        return subprocess.run(
            [
                "bash",
                "-c",
                'SCRIPT=test; source "$1"; guard_workspace_inventory "$2"',
                "-",
                str(LIB),
                str(self.inventory),
            ],
            cwd=self.checkout,
            env={**self.env, "INFINITO_SRC_DIR": str(src)},
            capture_output=True,
            text=True,
            check=False,
        )

    def unguarded(self, *argv, **pins):
        """Args:
        argv: the ansible command after its name, which comes first.
        pins: the environment the command runs with beside PATH and HOME.

        Returns:
            The completed process.
        """
        return subprocess.run(
            [str(BIN / argv[0]), *argv[1:]],
            cwd=self.checkout,
            env={**self.env, **pins},
            capture_output=True,
            text=True,
            check=False,
        )

    def ran(self):
        """Returns:
        Whether the planted code ran, resetting the marker.
        """
        ran = self.marker.exists()
        self.marker.unlink(missing_ok=True)
        return ran

    def test_a_plain_yaml_inventory_passes(self):
        self.inventory.write_text(
            "all:\n  hosts:\n    203.0.113.10:\n      ansible_user: admin\n",
            encoding="utf-8",
        )
        done = self.guard()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_an_ansible_cfg_of_the_checkout_loads_no_plugin(self):
        (self.checkout / "evil").mkdir()
        (self.checkout / "evil" / "evil.py").write_text(
            EVIL_VARS_PLUGIN.format(marker=str(self.marker)), encoding="utf-8"
        )
        (self.checkout / "ansible.cfg").write_text(
            "[defaults]\nvars_plugins = ./evil\n", encoding="utf-8"
        )
        self.inventory.write_text(
            "all:\n  hosts:\n    203.0.113.10: {}\n", encoding="utf-8"
        )
        done = self.guard()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.ran())
        with self.subTest(
            "negative control: without the pinned ANSIBLE_CONFIG the checkout's cfg loads it"
        ):
            self.unguarded("ansible-inventory", "-i", str(self.inventory), "--list")
            self.assertTrue(self.ran())

    def test_an_executable_inventory_is_refused_and_never_run(self):
        self.inventory.write_text(
            f"#!/bin/sh\ntouch {self.marker}\necho '{{}}'\n", encoding="utf-8"
        )
        self.inventory.chmod(0o755)
        done = self.guard()
        self.assertEqual(done.returncode, 2)
        self.assertIn("no plain YAML inventory", done.stderr)
        self.assertFalse(self.ran())
        with self.subTest("negative control: the default inventory plugins run it"):
            self.unguarded(
                "ansible-inventory",
                "-i",
                str(self.inventory),
                "--list",
                ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
            )
            self.assertTrue(self.ran())

    def test_an_inventory_plugin_file_is_refused_and_never_rendered(self):
        self.inventory.write_text(
            "plugin: ansible.builtin.generator\nhosts:\n"
            f"  name: \"h{{{{ lookup('pipe', 'touch {self.marker}') }}}}{{{{ x }}}}\"\n"
            "layers:\n  x: ['1']\n",
            encoding="utf-8",
        )
        done = self.guard()
        self.assertEqual(done.returncode, 2)
        self.assertFalse(self.ran())
        with self.subTest("negative control: the default inventory plugins render it"):
            self.unguarded(
                "ansible-inventory",
                "-i",
                str(self.inventory),
                "--list",
                ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
            )
            self.assertTrue(self.ran())

    def test_jinja_in_a_host_variable_is_refused_before_anything_renders_it(self):
        self.inventory.write_text(
            f"all:\n  hosts:\n    h1:\n      x: \"{{{{ lookup('pipe', 'touch {self.marker}') }}}}\"\n",
            encoding="utf-8",
        )
        done = self.guard()
        self.assertEqual(done.returncode, 2)
        self.assertIn("_meta.hostvars.h1.x", done.stderr)
        self.assertFalse(self.ran())
        with self.subTest(
            "negative control: a task reading the variable runs the lookup on the runner"
        ):
            self.unguarded(
                "ansible",
                "h1",
                "-i",
                str(self.inventory),
                "-c",
                "local",
                "-m",
                "ansible.builtin.debug",
                "-a",
                "var=x",
                ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
            )
            self.assertTrue(self.ran())

    def test_a_host_variable_shadowing_a_core_setting_is_refused(self):
        self.inventory.write_text(
            "all:\n  hosts:\n    h1:\n      STACK_HOST: localhost\n", encoding="utf-8"
        )
        done = self.guard()
        self.assertEqual(done.returncode, 2)
        self.assertIn(
            "_meta.hostvars.h1.STACK_HOST shadows a core setting", done.stderr
        )
        with self.subTest(
            "negative control: the host variable outranks the playbook's group_vars/all"
        ):
            playbook = self.root / "core"
            (playbook / "group_vars" / "all").mkdir(parents=True)
            (playbook / "group_vars" / "all" / "stack.yml").write_text(
                "STACK_HOST: stack-01\n", encoding="utf-8"
            )
            (playbook / "play.yml").write_text(
                "- hosts: h1\n  gather_facts: false\n  tasks:\n"
                '    - ansible.builtin.debug:\n        msg: "stack={{ STACK_HOST }}"\n',
                encoding="utf-8",
            )
            done = self.unguarded(
                "ansible-playbook",
                "-i",
                str(self.inventory),
                "-c",
                "local",
                str(playbook / "play.yml"),
                ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
            )
            self.assertIn("stack=localhost", done.stdout, done.stderr)

    def test_a_core_tree_without_ansible_cfg_is_refused(self):
        self.inventory.write_text(
            "all:\n  hosts:\n    203.0.113.10: {}\n", encoding="utf-8"
        )
        done = self.guard(src=self.root)
        self.assertEqual(done.returncode, 2)
        self.assertIn("holds no ansible.cfg", done.stderr)


if __name__ == "__main__":
    unittest.main()
