import configparser
import json
import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from ansible.plugins.test.core import TestModule as CoreTests
from jinja2 import Environment
from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "dsk-code"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
CORE = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"))
PROTECT = load_yaml_any(str(ROLE / "tasks" / "02_protect.yml"))
RETIRE = load_yaml_any(str(ROLE / "tasks" / "02_protect" / "retire.yml"))
PROFILES = load_yaml_any(str(ROLE / "tasks" / "01_claude_profiles.yml"))
GUARD_TASK = load_yaml_any(str(ROLE / "tasks" / "addons" / "python.yml"))[0]
PYTHON_ADDON = load_yaml_any(str(ROLE / ROLE_DIR_META_ADDONS / "python.yml"))
HOME = "/home/administrator"
UNITS = "/etc/systemd/system"
GUARD = {
    "search.ripgrep.maxThreads": 4,
    "files.watcherExclude": {
        "**/.worktrees/**": True,
        "**/.claude/worktrees/**": True,
    },
}
FLATPAK_VSCODIUM = f"{HOME}/.var/app/com.vscodium.codium/config/VSCodium"
FLATPAK_VSCODE = f"{HOME}/.var/app/com.visualstudio.code/config/Code"
SETTINGS = {
    ("code-oss", "Archlinux"): f"{HOME}/.config/Code - OSS/User/settings.json",
    ("vscodium", "Archlinux"): f"{HOME}/.config/VSCodium/User/settings.json",
    ("vscode", "Archlinux"): f"{HOME}/.config/Code/User/settings.json",
    ("vscodium", "Debian"): f"{FLATPAK_VSCODIUM}/User/settings.json",
    ("vscodium", "RedHat"): f"{FLATPAK_VSCODIUM}/User/settings.json",
    ("vscode", "Debian"): f"{FLATPAK_VSCODE}/User/settings.json",
    ("vscode", "RedHat"): f"{FLATPAK_VSCODE}/User/settings.json",
}


def render(expression, environment_class=NativeEnvironment, **context):
    environment = environment_class()
    environment.filters.update(CoreFilters().filters())
    environment.filters.update(MathFilters().filters())
    environment.tests.update(CoreTests().tests())
    return environment.from_string(expression).render(**context)


def holds(task, **context):
    when = task["when"]
    clauses = when if isinstance(when, list) else [when]
    return all(render("{{ " + clause + " }}", **context) for clause in clauses)


def walk(entries):
    for entry in entries:
        yield entry
        yield from walk(entry.get("block", []))


def include(file):
    return next(
        task for task in walk(CORE) if task.get("ansible.builtin.include_tasks") == file
    )


def addons(enabled, **config):
    return {
        "python": dict(
            PYTHON_ADDON, enabled=enabled, config=dict(PYTHON_ADDON["config"], **config)
        )
    }


def project_lookup(kind, *terms):
    if kind == "path_absolute":
        return str(PROJECT_ROOT / terms[0])
    if kind == "file":
        return read_text(terms[0])
    raise AssertionError(f"unexpected lookup {kind}")


def settings_path(flavor, family):
    context = {
        "code_flavor": flavor,
        "code_flavors": VARS["code_flavors"],
        "code_home": HOME,
        "ansible_facts": {"os_family": family},
        "lookup": project_lookup,
    }
    for name in ("code_package", "code_config_home", "code_user_settings"):
        context[name] = render(VARS[name], **context)
    return render(GUARD_TASK["ansible.builtin.command"]["argv"][3], **context)


def unit(name):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(read_text(str(ROLE / "files" / "systemd" / name)))
    return parser


class PythonAddonGuardTest(unittest.TestCase):
    def test_enabled_addon_guards_ripgrep_threads_and_nested_worktrees(self):
        self.assertEqual(
            render(VARS["code_python_guard"], code_addons=addons(True), code_home=HOME),
            GUARD,
        )

    def test_watcher_exclude_never_names_an_absolute_parent_of_the_workspace(self):
        guard = render(
            VARS["code_python_guard"], code_addons=addons(True), code_home=HOME
        )
        self.assertEqual(
            [key for key in guard["files.watcherExclude"] if not key.startswith("**/")],
            [],
        )

    def test_disabled_addon_contributes_no_settings(self):
        self.assertEqual(
            render(
                VARS["code_python_guard"], code_addons=addons(False), code_home=HOME
            ),
            {},
        )

    def test_python_addon_is_opt_in(self):
        self.assertIs(PYTHON_ADDON["enabled"], False)

    def test_settings_merge_runs_only_for_an_enabled_addon(self):
        task = include("addons/python.yml")
        self.assertTrue(holds(task, code_addons=addons(True)))
        self.assertFalse(holds(task, code_addons=addons(False)))

    def test_guard_reaches_the_settings_file_each_flavor_reads(self):
        command = GUARD_TASK["ansible.builtin.command"]
        self.assertIn(
            "roles/dsk-code/files/python/code_settings.py", command["argv"][2]
        )
        for (flavor, family), expected in SETTINGS.items():
            with self.subTest(flavor=flavor, family=family):
                self.assertEqual(settings_path(flavor, family), expected)
                stdin = render(
                    command["stdin"],
                    environment_class=Environment,
                    code_python_guard=render(
                        VARS["code_python_guard"],
                        code_addons=addons(True),
                        code_home=HOME,
                    ),
                )
                self.assertEqual(json.loads(stdin), GUARD)

    def test_editor_settings_keep_inventory_keys_and_add_the_guard(self):
        inventory = {
            "window.autoDetectColorScheme": True,
            "files.watcherExclude": {"**/node_modules/**": True},
        }
        settings = render(
            VARS["code_settings"],
            lookup=lambda *_: inventory,
            application_id="dsk-code",
            code_python_guard=GUARD,
        )
        self.assertEqual(
            settings,
            {
                "window.autoDetectColorScheme": True,
                "search.ripgrep.maxThreads": 4,
                "files.watcherExclude": {
                    "**/node_modules/**": True,
                    **GUARD["files.watcherExclude"],
                },
            },
        )

    def test_claude_profiles_receive_the_guarded_editor_settings(self):
        stdin = next(
            task["ansible.builtin.command"]["stdin"]
            for task in PROFILES
            if "stdin" in task.get("ansible.builtin.command", {})
        )
        payload = json.loads(
            render(
                stdin,
                environment_class=Environment,
                lookup=lambda *_: "",
                code_addons={
                    "claude-code": {
                        "enabled": True,
                        "mechanism": "extension",
                        "config": {
                            "extension_id": "anthropic.claude-code",
                            "gateway_url": "",
                            "profiles": [],
                            "unified": {},
                        },
                    }
                },
                code_settings=GUARD,
            )
        )
        self.assertEqual(payload["code_settings"], GUARD)

    def test_extension_install_takes_only_extension_addons(self):
        task = next(
            task
            for task in walk(CORE)
            if "--install-extension" in str(task.get("ansible.builtin.command"))
        )
        rendered = render(
            task["loop"],
            code_addons={
                "python": {"mechanism": "extension"},
                "theme": {"mechanism": "theme"},
            },
        )
        self.assertEqual([item["key"] for item in rendered], ["python"])


class CodeOssProtectionTest(unittest.TestCase):
    def protect(self, flavor, install):
        return render(
            include("02_protect.yml")["vars"]["code_protect"],
            code_flavor=flavor,
            code_install=install,
        )

    def test_protection_is_wanted_for_code_oss_only(self):
        self.assertEqual(set(VARS["code_flavors"]), {"code-oss", "vscodium", "vscode"})
        for flavor in VARS["code_flavors"]:
            with self.subTest(flavor=flavor):
                self.assertEqual(
                    self.protect(flavor, {"changed": True}), flavor == "code-oss"
                )

    def test_protection_is_not_wanted_for_an_editor_the_host_did_not_install(self):
        self.assertFalse(self.protect("code-oss", {"skipped": True}))

    def test_install_and_retirement_never_run_together(self):
        install, retire = PROTECT
        self.assertEqual(
            retire["ansible.builtin.include_tasks"], "02_protect/retire.yml"
        )
        for wanted in (True, False):
            with self.subTest(wanted=wanted):
                self.assertEqual(holds(install, code_protect=wanted), wanted)
                self.assertEqual(holds(retire, code_protect=wanted), not wanted)

    def test_retirement_removes_everything_the_install_puts_in_place(self):
        install, _ = PROTECT
        context = {
            "DIR_SYSTEM_SERVICE": UNITS,
            "code_protect_script": VARS["code_protect_script"],
            "code_protect_units": VARS["code_protect_units"],
        }
        copies = [task for task in install["block"] if "ansible.builtin.copy" in task]
        installed = {render(copies[0]["ansible.builtin.copy"]["dest"], **context)} | {
            render(copies[1]["ansible.builtin.copy"]["dest"], item=item, **context)
            for item in render(copies[1]["loop"], **context)
        }
        removal = next(task for task in RETIRE if "ansible.builtin.file" in task)
        self.assertEqual(len(installed), 3)
        self.assertEqual(set(render(removal["loop"], **context)), installed)

    def test_retirement_stops_the_timer_only_when_it_is_installed(self):
        look, stop = RETIRE[:2]
        self.assertEqual(
            render(look["ansible.builtin.stat"]["path"], DIR_SYSTEM_SERVICE=UNITS),
            f"{UNITS}/protect-code-oss.timer",
        )
        self.assertEqual(stop["ansible.builtin.systemd"]["state"], "stopped")
        self.assertIs(stop["ansible.builtin.systemd"]["enabled"], False)
        self.assertTrue(holds(stop, code_protect_timer={"stat": {"exists": True}}))
        self.assertFalse(holds(stop, code_protect_timer={"stat": {"exists": False}}))

    def test_service_runs_the_installed_script_on_the_live_roots(self):
        self.assertEqual(
            unit("protect-code-oss.service")["Service"]["ExecStart"].split(),
            [VARS["code_protect_script"], "/sys/fs/cgroup", "/proc", "/usr/lib"],
        )

    def test_service_holds_only_the_capabilities_the_script_needs(self):
        service = unit("protect-code-oss.service")["Service"]
        self.assertEqual(
            set(service["CapabilityBoundingSet"].split()),
            {"CAP_SYS_RESOURCE", "CAP_SYS_NICE", "CAP_DAC_OVERRIDE", "CAP_SYS_PTRACE"},
        )
        self.assertEqual(
            {
                key: service[key]
                for key in (
                    "NoNewPrivileges",
                    "ProtectSystem",
                    "ProtectHome",
                    "PrivateNetwork",
                    "LogLevelMax",
                )
            },
            {
                "NoNewPrivileges": "yes",
                "ProtectSystem": "strict",
                "ProtectHome": "read-only",
                "PrivateNetwork": "yes",
                "LogLevelMax": "notice",
            },
        )

    def test_timer_reapplies_the_protection_every_30_seconds(self):
        timer = unit("protect-code-oss.timer")
        self.assertEqual(timer["Timer"]["OnUnitActiveSec"], "30s")
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")
        enable = next(
            task["ansible.builtin.systemd"]
            for task in walk(PROTECT)
            if task.get("ansible.builtin.systemd", {}).get("enabled") is True
        )
        self.assertEqual(enable["name"], "protect-code-oss.timer")


if __name__ == "__main__":
    unittest.main()
