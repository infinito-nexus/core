"""The body_filter Lua the vhost write folds in is the file the template action writes.

``sys-front-inj-all/tasks/standalone.yml`` writes ``body_filter.lua`` through
``stack_host_template``; ``sys-stk-front-proxy`` renders it through
``lookup('template_shallow')`` and writes it in the same
``stack_host_contents`` call as ``http.conf`` and the vhost. The renders run
through Ansible's own template action and templar against the real lookups,
filters and include tree, once in the variable scope each path really sees.
"""

from __future__ import annotations

import copy
import re
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader
from ansible.template import Templar, trust_as_template

from plugins.action.stack_host_template import ActionModule as StackHostTemplate
from utils.cache import _reset_cache_for_tests
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.domains.default_primary import default_domain_primary
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)
from utils.tls_common import iter_domains

ROLES = PROJECT_ROOT / "roles"
FRONT = ROLES / "sys-stk-front-proxy"
INJ = ROLES / "sys-front-inj-all"
LUA_TEMPLATE = INJ / "templates" / "body_filter.lua.j2"
DOMAIN = default_domain_primary()
ONION = "b" * 56 + ".onion"
STARTERS = re.compile(
    r"name:\s*['\"]?(sys-stk-full|sys-stk-front-proxy)['\"]?\s*$", re.MULTILINE
)
INJECTION_PROVIDERS = (
    "web-svc-design",
    "web-app-matomo",
    "web-svc-logout",
    "web-app-dashboard",
)
SCENARIOS = (
    (True, False, True),
    (False, False, False),
    (True, True, False),
    (False, True, True),
)
INCLUDE = re.compile(r"\{%-?\s*include\s+(?P<expr>[^%]+?)\s*-?%\}")
LUA_ENTRY = (
    "([{'path': lookup('nginx', 'files.lua', front_proxy_domain), "
    "'content': lookup('template_shallow', lookup('path_absolute', "
    "'roles/sys-front-inj-all/templates/body_filter.lua.j2'), "
    "template_vars={'application_id': front_proxy_application_id, "
    "'domain': front_proxy_domain})}] "
    "if IS_STACK_HOST | bool else [])"
)
UNPINNED_ENTRY = LUA_ENTRY.replace(
    ", template_vars={'application_id': front_proxy_application_id, "
    "'domain': front_proxy_domain}",
    "",
)
MIRROR_MARKER = b"do\n    local pat = ([=[https://"
RICH = {
    "app_style_present": True,
    "app_style_file": "style.css",
    "app_style_css": "body { color: #123; }\n",
    "design_js_one_liner": "(function(){var s='\\\\n';window.__x=\"]=] ä ✓\";})();",
    "design_config_json": '{"title":"<A & B>","q":"\\"x\\""}',
    "logout_code_one_liner": "document.addEventListener('click',function(e){});  ",
    "iframe_init_code_one_liner": "window.parent.postMessage({h:1},'*');",
    "javascript_code_one_liner": "console.log('\\t{{ not a template }}');",
    "matomo_site_id": "7",
    "matomo_tracking_code_one_liner": "var _paq=window._paq=window._paq||[];",
}
SPARSE = {
    **dict.fromkeys(RICH, ""),
    "app_style_present": False,
}
EDGE_TEMPLATES = {
    "one_newline.j2": "a\n",
    "two_newlines.j2": "a\n\n",
    "no_newline.j2": "a",
    "only_newlines.j2": "\n\n\n",
    "blocks.j2": (
        "{% if flag %}\n  yes\n{% endif %}\n"
        "    {% for i in [1, 2] %}\n{{ i }}\n    {% endfor %}\n"
        "{%- if flag %} tight {% endif -%}\n"
        "{# comment #}\nend\n"
    ),
    "macro.j2": (
        "{% macro push(name) -%}\n{{ name }}[1] = [=[\n"
        "  {%- include 'one_newline.j2' -%}\n]=]\n{% endmacro %}\n"
        "{{ push('top') }}\n{{ push('head') }}"
    ),
    "carriage.j2": "a\r\nb\r\n{{ value }}\r\n",
    "unicode.j2": "ä ✓ {{ value }}\t\n",
    "backslash.j2": "x\\ny {{ '\\\\' }} \\\\ end\n",
}


def _trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, Mapping):
        return {key: _trusted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    return value


def _yaml(path: Path) -> dict:
    data = load_yaml_any(str(path), default_if_missing={})
    if not isinstance(data, Mapping):
        return {}
    return {key: _trusted(value) for key, value in data.items()}


def _task_with(path: Path, module: str) -> dict:
    return next(t for t in load_yaml_any(str(path)) if module in t)


def _normalised(text: str) -> str:
    return " ".join(text.split())


class _Shell:
    tmpdir = "/nonexistent/remote/tmp"


class _Connection:
    _shell = _Shell()


class _Task:
    async_val = 0
    check_mode = False

    def __init__(self, args: dict, search_path: list[str]) -> None:
        self.args = dict(args)
        self._search_path = list(search_path)

    def get_search_path(self) -> list[str]:
        return list(self._search_path)

    def copy(self) -> _Task:
        return _Task(self.args, self._search_path)


class _CapturingCopy:
    def __init__(self, task: _Task) -> None:
        self._task = task

    def run(self, task_vars=None) -> dict:
        source = Path(self._task.args["src"])
        return {
            "bytes": source.read_bytes(),  # nocheck: cache-read the action's own temp render, deleted right after
            "dest": self._task.args["dest"],
            "mode": self._task.args["mode"],
        }


class _ActionLoader:
    def get(self, name: str, task: _Task, **kwargs) -> _CapturingCopy:
        assert name == "ansible.legacy.copy", name
        return _CapturingCopy(task)


class _SharedLoader:
    action_loader = _ActionLoader()


def render_action(task_vars: dict, src: str, dest: str, search_path, **args) -> dict:
    """Run the real ``stack_host_template`` action up to the copy it hands off to.

    Args:
        task_vars: the variables the task sees.
        src: the ``src`` argument, resolved like the task resolves it.
        dest: the ``dest`` argument.
        search_path: the task's role search path.
        args: further template action arguments, e.g. ``lstrip_blocks``.

    Returns:
        ``{"bytes", "dest", "mode"}`` the copy module would receive.
    """
    loader = DataLoader()
    loader.set_basedir(str(PROJECT_ROOT))
    action = StackHostTemplate(
        task=_Task({"src": src, "dest": dest, **args}, search_path),
        connection=_Connection(),
        play_context=None,
        loader=loader,
        templar=Templar(loader=loader),
        shared_loader_obj=None,
    )
    action._shared_loader_obj = _SharedLoader()
    return action.run(task_vars=task_vars)


def render_expression(variables: dict, expression: str):
    loader = DataLoader()
    loader.set_basedir(str(PROJECT_ROOT))
    return Templar(loader=loader, variables=variables).template(
        trust_as_template(expression)
    )


def _outcome(render):
    try:
        return ("ok", render())
    except Exception as error:
        causes = []
        while error is not None:
            causes.append(str(error).replace("template_shallow", "template"))
            error = error.__cause__
        return ("error", causes[-1])


def front_proxy_roles() -> list[str]:
    """Return every role whose vhost ``sys-stk-front-proxy`` writes."""
    found = set()
    for name in iter_project_files(extensions=(".yml", ".j2"), exclude_tests=True):
        path = Path(name)
        if not path.is_relative_to(ROLES):
            continue
        parts = path.relative_to(ROLES).parts
        if len(parts) < 3 or parts[0] in ("sys-stk-full", FRONT.name):
            continue
        if parts[1:] == ("templates", "proxy.conf.j2") or (
            parts[1] == "tasks"
            and path.suffix == ".yml"
            and STARTERS.search(read_text(name))
        ):
            found.add(parts[0])
    return sorted(found)


def lua_include_tree() -> list[Path]:
    """Return the Lua template and every template its includes can reach."""
    seen: list[Path] = []
    pending = [LUA_TEMPLATE]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.append(path)
        for match in INCLUDE.finditer(read_text(str(path))):
            expr = match["expr"]
            if "~ f ~" in expr:
                pending.extend(sorted(ROLES.glob("sys-front-inj-*/templates/*_sub.j2")))
            else:
                pending.extend(
                    PROJECT_ROOT / name for name in re.findall(r"'([^']+\.j2)'", expr)
                )
    return seen


class _Harness:
    def __init__(self) -> None:
        self.group_vars: dict = {}
        for path in sorted((PROJECT_ROOT / "group_vars" / "all").glob("*.yml")):
            self.group_vars.update(_yaml(path))
        vhost_tasks = FRONT / "tasks" / "vhost.yml"
        self.deploy = _task_with(vhost_tasks, "stack_host_contents")
        self.main = _task_with(FRONT / ROLE_FILE_TASKS_MAIN, "ansible.builtin.set_fact")
        self.inj = _task_with(INJ / ROLE_FILE_TASKS_MAIN, "set_fact")
        self.lua_task = _task_with(
            INJ / "tasks" / "standalone.yml", "stack_host_template"
        )
        filter_loader.add_directory(str(INJ / "filter_plugins"))

    def base(self, app: str, tls: bool, tor: bool, providers: bool) -> dict:
        groups = (
            ["svc-prx-openresty"]
            + (["svc-net-tor"] if tor else [])
            + (list(INJECTION_PROVIDERS) if providers else [])
        )
        return {
            **self.group_vars,
            **_yaml(FRONT / ROLE_FILE_DEFAULTS_MAIN),
            **_yaml(ROLES / app / ROLE_FILE_DEFAULTS_MAIN),
            **_yaml(ROLES / app / ROLE_FILE_VARS_MAIN),
            "playbook_dir": str(PROJECT_ROOT),
            "inventory_hostname": "localhost",
            "group_names": groups,
            "groups": {group: ["localhost"] for group in groups},
            "DOMAIN_PRIMARY": DOMAIN,
            "SYSTEM_EMAIL_DOMAIN": DOMAIN,
            "TLS_ENABLED": tls,
            "applications": (
                {"svc-net-tor": {"services": {"tor": {"node": ONION}}}} if tor else {}
            ),
            "users": {},
            "IS_STACK_HOST": True,
            "RESOURCE_HOST_CPUS_OVERRIDE": 8,
            "RESOURCE_HOST_MEM_MB_OVERRIDE": 32768,
            "application_id": app,
        }

    def vhosts(self, variables: dict, app: str) -> list[str]:
        domains = render_expression(variables, "{{ lookup('domains') }}").get(app)
        found: list[str] = []
        for domain in iter_domains(domains) if domains else []:
            for vhost in render_expression(
                variables, f"{{{{ lookup('network_siblings', '{domain}') }}}}"
            ):
                if vhost not in found:
                    found.append(vhost)
        return found

    def scopes(self, app: str, tls: bool, tor: bool, providers: bool, facts: dict):
        """Yield ``(vhost, action_task_vars, fold_task_vars)`` per vhost of ``app``.

        Args:
            app: the application whose vhosts are rendered.
            tls: the inventory ``TLS_ENABLED``.
            tor: whether ``svc-net-tor`` serves the host with a node onion.
            providers: whether the injection providers run on the host.
            facts: the injection facts the ``sys-front-inj-*`` roles set.
        """
        variables = self.base(app, tls, tor, providers)
        variables.update(_yaml(FRONT / ROLE_FILE_VARS_MAIN))
        main_facts = Templar(loader=DataLoader(), variables=variables).template(
            _trusted(self.main["ansible.builtin.set_fact"])
        )
        for vhost in self.vhosts(variables, app):
            shared = {
                **variables,
                **main_facts,
                "front_proxy_domain": vhost,
                "domain": vhost,
            }
            inj_scope = {
                **shared,
                **_yaml(INJ / ROLE_FILE_DEFAULTS_MAIN),
                **_yaml(INJ / ROLE_FILE_VARS_MAIN),
            }
            inj_facts = Templar(loader=DataLoader(), variables=inj_scope).template(
                _trusted(self.inj["set_fact"])
            )
            shared.update(inj_facts)
            shared.update(facts)
            for feature in ("logout", "dashboard"):
                if inj_facts["inj_enabled"].get(feature):
                    shared.update(
                        _yaml(
                            ROLES / f"sys-front-inj-{feature}" / ROLE_FILE_DEFAULTS_MAIN
                        )
                    )
                    shared.update(
                        _yaml(ROLES / f"sys-front-inj-{feature}" / ROLE_FILE_VARS_MAIN)
                    )
            action_vars = {
                **shared,
                **_yaml(INJ / ROLE_FILE_DEFAULTS_MAIN),
                **_yaml(INJ / ROLE_FILE_VARS_MAIN),
                "ansible_search_path": [str(INJ), str(PROJECT_ROOT)],
            }
            fold_vars = {
                **shared,
                **_trusted(self.deploy["vars"]),
                "ansible_search_path": [str(FRONT), str(PROJECT_ROOT)],
            }
            yield vhost, action_vars, fold_vars

    def render_pair(self, action_vars: dict, fold_vars: dict):
        def action():
            dest = render_expression(
                action_vars, self.lua_task["stack_host_template"]["dest"]
            )
            result = render_action(
                action_vars,
                self.lua_task["stack_host_template"]["src"],
                dest,
                [str(INJ), str(INJ / "tasks")],
                mode=self.lua_task["stack_host_template"]["mode"],
            )
            return (result["dest"], result["bytes"], result["mode"])

        return _outcome(action), self.fold(fold_vars, LUA_ENTRY)

    def fold(self, fold_vars: dict, entry: str):
        def render():
            [rendered] = render_expression(fold_vars, "{{ " + entry + " }}")
            return (
                rendered["path"],
                rendered["content"].encode("utf-8"),
                self.deploy["stack_host_contents"]["mode"],
            )

        return _outcome(render)


class TestTheFoldRendersTheExactCallSite(unittest.TestCase):
    def test_the_deploy_task_carries_the_rendered_lua_entry(self) -> None:
        harness = _Harness()
        files = harness.deploy["stack_host_contents"]["files"]
        self.assertIn(_normalised(LUA_ENTRY), _normalised(files))

    def test_no_template_of_the_lua_tree_reads_template_action_only_vars(self) -> None:
        tree = lua_include_tree()
        self.assertGreater(len(tree), 9)
        for path in tree:
            with self.subTest(template=str(path.relative_to(PROJECT_ROOT))):
                self.assertNotRegex(
                    read_text(str(path)),
                    r"\btemplate_(destpath|host|uid|path|fullpath|mtime|run_date)\b|\bansible_managed\b",
                )


class TestEdgeCaseTemplatesRenderAlike(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        (cls.root / "templates").mkdir()
        for name, body in EDGE_TEMPLATES.items():
            (cls.root / "templates" / name).write_bytes(body.encode("utf-8"))
        cls.variables = {
            "flag": True,
            "value": "v\\1 ]=] ä",
            "IS_STACK_HOST": True,
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _action(self, name: str, **args) -> bytes:
        task_vars = {**self.variables, "ansible_search_path": [str(self.root)]}
        return render_action(task_vars, name, "/x/" + name, [str(self.root)], **args)[
            "bytes"
        ]

    def _lookup(self, name: str, plugin: str = "template_shallow") -> bytes:
        variables = {**self.variables, "ansible_search_path": [str(self.root)]}
        path = self.root / "templates" / name
        return render_expression(
            variables, f"{{{{ lookup('{plugin}', '{path}') }}}}"
        ).encode("utf-8")

    def test_every_edge_case_renders_byte_identical(self) -> None:
        for name in EDGE_TEMPLATES:
            with self.subTest(template=name):
                action = self._action(name)
                self.assertEqual(self._lookup(name), action)
                self.assertEqual(self._lookup(name, "template"), action)

    def test_the_trailing_newlines_survive_both_paths(self) -> None:
        self.assertEqual(self._lookup("one_newline.j2"), b"a\n")
        self.assertEqual(self._lookup("two_newlines.j2"), b"a\n\n")
        self.assertEqual(self._lookup("no_newline.j2"), b"a")

    def test_a_whitespace_semantics_difference_is_detected(self) -> None:
        self.assertNotEqual(
            self._action("blocks.j2", lstrip_blocks=True), self._lookup("blocks.j2")
        )
        self.assertNotEqual(
            self._action("blocks.j2", trim_blocks=False), self._lookup("blocks.j2")
        )


class TestEveryRoleRendersTheSameLua(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.roles = front_proxy_roles()
        cls.harness = harness = _Harness()
        cls.cases = []
        cls.mutated = []
        cls.mirrored = []
        for tls, tor, providers in SCENARIOS:
            _reset_cache_for_tests()
            index = 0
            for app in cls.roles:
                for vhost, action_vars, fold_vars in harness.scopes(
                    app, tls, tor, providers, RICH if index % 2 == 0 else SPARSE
                ):
                    snapshot = copy.deepcopy(fold_vars)
                    action, fold = harness.render_pair(action_vars, fold_vars)
                    if fold_vars != snapshot:
                        cls.mutated.append((app, vhost, tls, tor, providers))
                    case = (app, vhost, tls, tor, providers, index % 2)
                    cls.cases.append((case, action, fold))
                    if (
                        action[0] == "ok"
                        and MIRROR_MARKER in action[1][1]
                        and len(cls.mirrored) < 3
                    ):
                        cls.mirrored.append((case, action, fold_vars))
                    index += 1
        _reset_cache_for_tests()

    def test_the_scan_finds_every_front_proxy_role(self) -> None:
        self.assertGreater(len(self.roles), 90)
        self.assertIn("web-app-wordpress", self.roles)
        self.assertIn("web-svc-html", self.roles)

    def test_the_action_and_the_fold_agree_byte_for_byte(self) -> None:
        for case, action, fold in self.cases:
            with self.subTest(case=case):
                self.assertEqual(fold, action)

    def test_almost_every_case_renders(self) -> None:
        rendered = sum(action[0] == "ok" for _, action, _ in self.cases)
        self.assertGreater(rendered, 0.95 * len(self.cases))
        self.assertGreater(rendered, 4 * len(self.roles))

    def test_the_cases_reach_every_branch_of_the_template(self) -> None:
        bodies = [
            action[1][1].decode("utf-8")
            for _, action, _ in self.cases
            if action[0] == "ok"
        ]
        onion = [
            c for c, a, _ in self.cases if c[1].endswith(".onion") and a[0] == "ok"
        ]
        self.assertTrue(onion)
        for marker in (
            "top_snippets[#top_snippets + 1]",
            "head_snippets[#head_snippets + 1]",
            "body_snippets[#body_snippets + 1]",
            'host:sub(-6) == ".onion"',
            MIRROR_MARKER.decode("utf-8"),
            "data-design=",
            "?version=",
        ):
            with self.subTest(marker=marker):
                self.assertTrue(any(marker in body for body in bodies))
        self.assertTrue(any("data-design=" not in body for body in bodies))

    def test_the_shallow_render_leaves_every_variable_untouched(self) -> None:
        self.assertEqual(self.mutated, [])

    def test_every_render_compares_alike_as_text_and_as_bytes(self) -> None:
        for case, action, _ in self.cases:
            if action[0] == "ok":
                with self.subTest(case=case):
                    self.assertNotIn(b"\r", action[1][1])
                    action[1][1].decode("utf-8")

    def test_an_outranking_include_param_cannot_reach_the_lua(self) -> None:
        self.assertEqual(len(self.mirrored), 3)
        for case, action, fold_vars in self.mirrored:
            _reset_cache_for_tests()
            for drift in ({"domain": DOMAIN}, {"application_id": "web-svc-html"}):
                drifted = {**fold_vars, **drift}
                with self.subTest(case=case, drift=drift):
                    self.assertEqual(self.harness.fold(drifted, LUA_ENTRY), action)
                    self.assertNotEqual(
                        self.harness.fold(drifted, UNPINNED_ENTRY), action
                    )
        _reset_cache_for_tests()


if __name__ == "__main__":
    unittest.main()
