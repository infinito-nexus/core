from __future__ import annotations

import re
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_HANDLERS_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ROLES = PROJECT_ROOT / "roles"
VHOST = ROLES / "sys-stk-front-proxy" / "tasks" / "vhost.yml"
INJ_TASKS = ROLES / "sys-front-inj-all" / ROLE_FILE_TASKS_MAIN
INJ_STANDALONE = ROLES / "sys-front-inj-all" / "tasks" / "standalone.yml"
LUA_PATH = "lookup('nginx', 'files.lua', front_proxy_domain)"
LUA_SOURCE = "'roles/sys-front-inj-all/templates/body_filter.lua.j2'"
LUA_SCOPE = (
    "template_vars={'application_id': front_proxy_application_id, "
    "'domain': front_proxy_domain}"
)
INCLUDE_KEYS = ("include_role", "ansible.builtin.include_role", "import_role")


def _tasks(path):
    return load_yaml_any(str(path)) or []


def _named(tasks, prefix):
    return next(t for t in tasks if str(t.get("name", "")).startswith(prefix))


def _walk(tasks):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _walk(task.get(key) or [])


def _includes_of(role):
    found = []
    for name, content in sorted(
        iter_project_files_with_content(extensions=(".yml",), exclude_tests=True)
    ):
        path = Path(name)
        if not path.is_relative_to(ROLES) or "tasks" not in path.parts:
            continue
        if role not in content:
            continue
        for task in _walk(_tasks(path)):
            for key in INCLUDE_KEYS:
                spec = task.get(key)
                if isinstance(spec, dict) and spec.get("name") == role:
                    found.append((path.relative_to(PROJECT_ROOT), task))
    return found


def _flat(text):
    return " ".join(str(text).split())


class TestEveryCallerDecidesWhoWritesTheLua(unittest.TestCase):
    def test_only_the_vhost_write_enters_without_the_lua_task(self):
        entries = {
            str(path): next(task[key] for key in INCLUDE_KEYS if key in task).get(
                "tasks_from"
            )
            for path, task in _includes_of("sys-front-inj-all")
        }
        self.assertEqual(
            entries,
            {
                "roles/sys-stk-front-proxy/tasks/vhost.yml": None,
                "roles/web-app-matomo/tasks/08_reinject_consumers/vhosts.yml": "standalone.yml",
            },
        )

    def test_the_main_entry_writes_no_lua(self):
        self.assertNotIn("body_filter", read_text(str(INJ_TASKS)))
        self.assertNotIn("stack_host_template", read_text(str(INJ_TASKS)))

    def test_the_standalone_entry_builds_the_injection_then_writes_the_lua(self):
        build, lua = _tasks(INJ_STANDALONE)
        self.assertEqual(build["ansible.builtin.include_tasks"], "main.yml")
        self.assertEqual(lua["stack_host_template"]["src"], "body_filter.lua.j2")
        self.assertEqual(lua["notify"], "reload-openresty")
        self.assertNotIn("when", lua)


class TestTheVhostWriteCarriesTheLua(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = _tasks(VHOST)
        cls.deploy = _named(cls.tasks, "🚀 Deploy NGINX config")
        cls.files = _flat(cls.deploy["stack_host_contents"]["files"])

    def test_the_lua_is_the_first_file_and_skipped_off_the_stack_host(self):
        lua = self.files.index(LUA_PATH)
        self.assertLess(lua, self.files.index("protocol='http'"))
        self.assertLess(lua, self.files.index("front_proxy_domain_conf_dst_resolved"))
        self.assertIn(
            f"lookup('template_shallow', lookup('path_absolute', {LUA_SOURCE}), "
            f"{LUA_SCOPE})}}] if IS_STACK_HOST | bool else [])",
            self.files,
        )

    def test_the_lua_scope_matches_the_include_params(self):
        include = _named(self.tasks, "📌 CSP/INJ")["vars"]
        self.assertEqual(
            include,
            {
                "application_id": "{{ front_proxy_application_id }}",
                "domain": "{{ front_proxy_domain }}",
            },
        )
        self.assertIn(LUA_SCOPE, self.files)

    def test_the_lua_renders_from_the_template_the_action_rendered(self):
        inj = _named(_tasks(INJ_STANDALONE), "📄 Render body_filter Lua")
        self.assertIn(
            f"'{'roles/sys-front-inj-all/templates/'}{inj['stack_host_template']['src']}'",
            self.files,
        )
        self.assertEqual(
            _flat(inj["stack_host_template"]["dest"]),
            "{{ " + LUA_PATH.replace("front_proxy_domain", "domain") + " }}",
        )

    def test_mode_handler_and_diff_match_the_action(self):
        inj = _named(_tasks(INJ_STANDALONE), "📄 Render body_filter Lua")
        args = self.deploy["stack_host_contents"]
        self.assertEqual(args["mode"], inj["stack_host_template"]["mode"])
        self.assertEqual(self.deploy["notify"], inj["notify"])
        self.assertEqual(args["diff_paths"], ["{{ " + LUA_PATH + " }}"])

    def test_injection_runs_before_the_write_and_the_recheck_after_the_reload(self):
        names = [str(t.get("name", "")) for t in self.tasks]
        order = [
            next(i for i, n in enumerate(names) if n.startswith(prefix))
            for prefix in (
                "📌 CSP/INJ",
                "🚀 Deploy NGINX config",
                "🔄 Restart Webserver",
                "🔁 Re-check",
            )
        ]
        self.assertEqual(order, sorted(order))
        recheck = _named(self.tasks, "🔁 Re-check")
        probe, redeploy, flush = recheck["block"]
        self.assertIn("uri_probe", probe)
        self.assertEqual(redeploy["notify"], "restart-openresty")
        self.assertEqual(flush["ansible.builtin.meta"], "flush_handlers")
        self.assertEqual(recheck["when"], "front_proxy_vhost_changed")


class TestALuaOnlyChangeSkipsTheVhostRecheck(unittest.TestCase):
    def _vhost_changed(self, changed, paths):
        expression = load_yaml_any(
            str(ROLES / "sys-stk-front-proxy" / ROLE_FILE_VARS_MAIN)
        )["front_proxy_vhost_changed"]
        variables = {
            "nginx_conf": {"changed": changed, "changed_paths": paths},
            "front_proxy_domain_conf_dst_resolved": "/etc/nginx/conf.d/x.conf",
        }
        return Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template(expression)
        )

    def test_only_a_vhost_change_triggers_the_recheck(self):
        lua = "/etc/nginx/conf.d/lua/x.lua"
        self.assertFalse(self._vhost_changed(True, [lua]))
        self.assertTrue(self._vhost_changed(True, [lua, "/etc/nginx/conf.d/x.conf"]))
        self.assertFalse(self._vhost_changed(False, []))

    def test_the_handler_both_writers_notify_exists(self):
        handlers = read_text(str(ROLES / "svc-prx-openresty" / ROLE_FILE_HANDLERS_MAIN))
        self.assertRegex(
            handlers, re.compile(r"^\s*listen: reload-openresty$", re.MULTILINE)
        )


if __name__ == "__main__":
    unittest.main()
