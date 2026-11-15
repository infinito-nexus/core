import io
import json
import sys
import types
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/dsk-blender"
ADDONS = "/home/alice/.config/blender/5.2/scripts/addons"
BANNER = "Blender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-22 17:10:25)\n"


def _yaml(relative):
    return load_yaml_str(read_text(str(ROLE / relative)))


def _tasks():
    for task in _yaml("tasks/addons/mcp-for-blender.yml"):
        yield task
        yield from task.get("block", [])


def _task(fragment):
    return next(task for task in _tasks() if fragment in task["name"])


def _render(template, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _holds(condition, **variables):
    return _render("{{ (" + condition + ") | bool }}", **variables)


def _probe_stdout():
    expression = _task("user addons directory")["ansible.builtin.command"]["argv"][-1]
    bpy = types.SimpleNamespace(
        utils=types.SimpleNamespace(user_resource=lambda kind, path, create: ADDONS)
    )
    out = io.StringIO()
    with mock.patch.dict(sys.modules, {"bpy": bpy}), redirect_stdout(out):
        exec(expression, {})
    return out.getvalue() + BANNER


def _codex_list(*names):
    return {"stdout": json.dumps([{"name": name} for name in names])}


class TestAddonActivation(unittest.TestCase):
    def test_addons_dir_survives_the_banner_blender_prints_after_the_probe(self):
        resolved = _render(
            _yaml(ROLE_FILE_VARS_MAIN)["blender_mcp_addons_dir"],
            blender_addons_probe={"stdout": _probe_stdout()},
        )
        self.assertEqual(resolved, ADDONS)

    def test_install_addon_targets_the_probed_dir_explicitly(self):
        argv = _task("Install the Blender side")["ansible.builtin.command"]["argv"]
        self.assertEqual(
            argv[1:], ["install-addon", "--addons-dir", "{{ blender_mcp_addons_dir }}"]
        )

    def test_enable_runs_the_role_script_for_the_declared_module(self):
        argv = _task("Enable the Blender MCP add-on")["ansible.builtin.command"]["argv"]
        self.assertEqual(
            argv[argv.index("--python-expr") + 1],
            "{{ lookup('file', 'python/addon_enable.py') }}",
        )
        self.assertEqual(argv[argv.index("--") + 1], "{{ blender_mcp_addon_module }}")

    def test_enable_fails_the_task_when_the_script_raises(self):
        argv = _task("Enable the Blender MCP add-on")["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[argv.index("--python-exit-code") + 1], "1")

    def test_declared_module_is_the_file_install_addon_writes(self):
        config = _yaml(f"{ROLE_DIR_META_ADDONS}/mcp-for-blender.yml")["config"]
        self.assertEqual(config["module"], "blender_mcp")

    def test_enable_reports_change_only_when_it_saved_the_preferences(self):
        changed_when = _task("Enable the Blender MCP add-on")["changed_when"]
        result = {"stdout": "BlenderMCP addon registered\nADDON=present\n"}
        self.assertFalse(_holds(changed_when, blender_mcp_addon_enable=result))
        result = {"stdout": "ADDON=enabled\n"}
        self.assertTrue(_holds(changed_when, blender_mcp_addon_enable=result))


class TestClaudeRegistration(unittest.TestCase):
    def test_claude_launches_the_absolute_server_path(self):
        argv = _task("Register the Blender MCP server with Claude")[
            "ansible.builtin.command"
        ]["argv"]
        self.assertEqual(argv[-1], "{{ blender_mcp_bin }}")


class TestCodexRegistration(unittest.TestCase):
    def test_codex_service_follows_the_codex_role(self):
        codex = _yaml(ROLE_FILE_META_SERVICES)["codex"]
        for flag in ("enabled", "shared"):
            on = _render(codex[flag], group_names=["dsk-blender", "dsk-gnt-codex"])
            off = _render(codex[flag], group_names=["dsk-blender", "dsk-gnt-claude"])
            self.assertEqual((on, off), (True, False), flag)

    def test_codex_block_is_gated_on_the_codex_service(self):
        block = _task("Wire the Blender MCP server into Codex")
        self.assertEqual(block["when"], "blender_mcp_codex_enabled | bool")
        self.assertIn(
            "'services.codex.enabled'",
            _yaml(ROLE_FILE_VARS_MAIN)["blender_mcp_codex_enabled"],
        )

    def test_codex_add_is_skipped_when_codex_already_carries_the_server(self):
        when = _task("Register the Blender MCP server with Codex")["when"]
        listed = _codex_list("github", "blender")
        self.assertFalse(
            _holds(
                when, blender_mcp_server_name="blender", blender_mcp_codex_list=listed
            )
        )

    def test_codex_add_runs_when_only_a_similar_name_is_listed(self):
        when = _task("Register the Blender MCP server with Codex")["when"]
        listed = _codex_list("blender-docs")
        self.assertTrue(
            _holds(
                when, blender_mcp_server_name="blender", blender_mcp_codex_list=listed
            )
        )

    def test_codex_add_launches_the_absolute_server_path(self):
        argv = _task("Register the Blender MCP server with Codex")[
            "ansible.builtin.command"
        ]["argv"]
        self.assertEqual(
            argv,
            [
                "codex",
                "mcp",
                "add",
                "{{ blender_mcp_server_name }}",
                "--",
                "{{ blender_mcp_bin }}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
