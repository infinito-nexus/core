from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from .test_stack_entry import _write

UNSITED = "web-app-gitlab"
SITED = "web-app-delta"
DOMAINS = {UNSITED: "gitlab.example", SITED: "delta.example"}
WEB_SVC = "web-svc-pulse"
WEB_SVC_DOMAIN = "pulse.example"
SITE_IDS = {
    "gitlab.example": "8",
    "delta.example": "9",
    WEB_SVC_DOMAIN: "5",
    "matomo.example": "1",
}
EARLIER_PLAY = "-- rendered by an earlier play"
HIDDEN_ENTRY = 'a[href="/users/sign_up"]'
REAL_ROLES = (
    "svc-stack",
    "sys-front-inj-all",
    "sys-front-inj-javascript",
    "sys-front-inj-matomo",
)
REAL_FILES = (
    Path("roles/web-app-gitlab/templates/javascript.js.j2"),
    Path("roles/web-app-matomo/tasks/08_reinject_consumers.yml"),
    Path("roles/web-app-matomo") / ROLE_FILE_VARS_MAIN,
    Path("group_vars/all/24_stack.yml"),
)
STUB_ROLES = (
    "sys-svc-nss",
    "sys-stk-front-base",
    "sys-front-tls",
    "sys-svc-webserver-core",
    "sys-svc-cdn",
)
SCRIPT = re.compile(
    r'<script data-matomo-site-id="(?P<site>[^"]*)">(?P<code>.*?)</script>'
)

STUB_RESOLVE = """---
- name: Answer the site id the stub Matomo knows, to a caller that holds a token
  ansible.builtin.set_fact:
    matomo_site_id: >-
      {{ stub_site_ids.get(domain, '')
         if (matomo_token_override | default('')) or (stub_stored_token | default(''))
         else '' }}
"""

CONSUMER = """---
- name: Serve the own front through svc-stack
  ansible.builtin.include_role:
    name: svc-stack
    tasks_from: consumer/front.yml
"""

STUB_LOOKUP = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{RESULT}]
"""

STUB_PROBE = """from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        return {"changed": False, "status": 200}
"""

LOOKUPS = {
    "applications": (
        f"{{{UNSITED!r}: {{'services': {{'matomo': {{'enabled': True}}, "
        f"'javascript': {{'enabled': True}}}}}}, "
        f"{SITED!r}: {{'services': {{'matomo': {{'enabled': True}}}}}}, "
        f"{WEB_SVC!r}: {{'services': {{'matomo': {{'enabled': True}}}}}}}}"
    ),
    "roles_with_service": f"[{{'id': {WEB_SVC!r}}}, {{'id': {UNSITED!r}}}]",
    "config": (
        "'sub' if terms[1].endswith('tracking.scope') "
        "else (True if terms[1].startswith('services.openresty.') else terms[2])"
    ),
    "domain": f"{ ({**DOMAINS, WEB_SVC: WEB_SVC_DOMAIN})!r}.get(terms[0], 'matomo.example')",
    "domains": "terms[1]",
    "network_siblings": "[terms[0]]",
    "nginx": (
        "variables['lua_dir'] + '/' + terms[1] "
        "+ ('.lua' if terms[0] == 'files.lua' else '.conf')"
    ),
    "tls": (
        "{'enabled': False, 'protocols.web': 'https', 'domain': terms[0]}.get("
        "terms[1], 'https://' + terms[0].replace('web-app-matomo', 'matomo.example') + '/')"
    ),
    "debug": "False",
    "field_locks": "{'locks': {}, 'languages': None}",
    "i18n_catalogue": "{}",
}

PLAYBOOK = """---
- name: Serve two fronts through svc-stack before Matomo installs, then let Matomo give them their sites
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    webserver_csp_hashes_extra_by_vhost: {}
  handlers:
    - name: Stand in for the OpenResty reload
      listen: reload-openresty
      ansible.builtin.command:
        cmd: "true"
      register: openresty_reload

    - name: Stand in for the OpenResty restart
      listen: restart-openresty
      ansible.builtin.debug:
        msg: restart
  tasks:
    - name: Serve the front of a consumer whose site Matomo does not know yet
      ansible.builtin.include_role:
        name: web-app-gitlab
      vars:
        stub_site_ids: {}

    - name: Serve the front of a consumer whose site Matomo already knows
      ansible.builtin.include_role:
        name: web-app-delta
      vars:
        stub_site_ids: {delta.example: "9"}
        stub_stored_token: stored

    - name: Keep what the fronts left for the CSP header and for Matomo
      ansible.builtin.set_fact:
        stub_first_csp: "{{ webserver_csp_hashes_extra_by_vhost }}"
        stub_recorded: "{{ stack_matomo_unsited }}"

    - name: Keep the Lua every front rendered
      ansible.builtin.copy:
        src: "{{ lua_dir }}/{{ item }}.lua"
        dest: "{{ first_dir }}/{{ item }}.lua"
        remote_src: true
        mode: "0644"
      loop: "{{ consumer_domains }}"

    - name: Leave the Lua a web-svc consumer got from an earlier play
      ansible.builtin.copy:
        dest: "{{ lua_dir }}/{{ web_svc_domain }}.lua"
        content: "{{ earlier_play }}"
        mode: "0644"

    - name: Let Matomo re-inject its consumers the way its install path does
      ansible.builtin.include_role:
        name: web-app-matomo
        tasks_from: 08_reinject_consumers.yml
      vars:
        matomo_token_value: installed
        stub_site_ids: "{{ site_ids }}"

    - name: Report what happened
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: >-
          {{ {'first_csp': stub_first_csp, 'recorded': stub_recorded,
              'left': stack_matomo_unsited | list} | to_json }}
        mode: "0644"
"""


def _build(workdir: Path) -> None:
    """Args:
    workdir: an empty directory that becomes the playbook directory.
    """
    for role in REAL_ROLES:
        shutil.copytree(
            PROJECT_ROOT / "roles" / role,
            workdir / "roles" / role,
            ignore=shutil.ignore_patterns("__pycache__", "filter_plugins"),
        )
    for path in REAL_FILES:
        _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
    shutil.copytree(
        PROJECT_ROOT / "roles/web-app-matomo/tasks/08_reinject_consumers",
        workdir / "roles/web-app-matomo/tasks/08_reinject_consumers",
    )
    _write(workdir / "roles/sys-front-inj-matomo/tasks/resolve_site.yml", STUB_RESOLVE)
    for role in STUB_ROLES:
        _write(workdir / "roles" / role / ROLE_FILE_TASKS_MAIN, "---\n[]\n")
    for app in DOMAINS:
        _write(workdir / "roles" / app / ROLE_FILE_TASKS_MAIN, CONSUMER)
        _write(
            workdir / "roles" / app / "templates/proxy.conf.j2",
            "server { server_name {{ domain }}; }\n",
        )
    _write(
        workdir / "roles" / UNSITED / ROLE_FILE_VARS_MAIN,
        f"---\napplication_id: {UNSITED}\n"
        f"GITLAB_LOGIN_HIDDEN_ENTRIES: [{json.dumps(HIDDEN_ENTRY)}]\n",
    )
    for app in (SITED, WEB_SVC):
        _write(
            workdir / "roles" / app / ROLE_FILE_VARS_MAIN,
            f"---\napplication_id: {app}\n",
        )
    for name, result in LOOKUPS.items():
        _write(workdir / f"lookup/{name}.py", STUB_LOOKUP.replace("{RESULT}", result))
    for action in ("stack_host_contents", "stack_host_template"):
        _write(
            workdir / f"action/{action}.py",
            read_text(str(PROJECT_ROOT / f"plugins/action/{action}.py")),
        )
    _write(workdir / "action/uri_probe.py", STUB_PROBE)
    _write(
        workdir / "library/stack_host_contents.py",
        read_text(str(PROJECT_ROOT / "library/stack_host_contents.py")),
    )
    _write(workdir / "play.yml", PLAYBOOK)


def run_fronts() -> dict:
    """Returns:
        the CSP snippets the fronts registered, the record they left, the
        record left after Matomo ran, and the Lua of every vhost before and
        after Matomo ran.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        _build(workdir)
        lua_dir, first_dir = workdir / "lua", workdir / "first"
        lua_dir.mkdir()
        first_dir.mkdir()
        report = workdir / "report.json"
        _write(
            workdir / "extra.json",
            json.dumps(
                {
                    "IS_STACK_HOST": True,
                    "MASK_CREDENTIALS_IN_LOGS": False,
                    "DOMAIN_PRIMARY": "example",
                    "lua_dir": str(lua_dir),
                    "first_dir": str(first_dir),
                    "consumer_domains": sorted(DOMAINS.values()),
                    "web_svc_domain": WEB_SVC_DOMAIN,
                    "earlier_play": EARLIER_PLAY,
                    "site_ids": SITE_IDS,
                    "report_out": str(report),
                }
            ),
        )
        env = {
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": f"{workdir / 'lookup'}:{PROJECT_ROOT / 'plugins/lookup'}",
            "ANSIBLE_FILTER_PLUGINS": ":".join(
                str(PROJECT_ROOT / path)
                for path in (
                    "roles/sys-front-inj-all/filter_plugins",
                    "roles/svc-stack/filter_plugins",
                    "plugins/filter",
                )
            ),
            "ANSIBLE_ACTION_PLUGINS": str(workdir / "action"),
            "ANSIBLE_LIBRARY": str(workdir / "library"),
        }
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                str(workdir / "play.yml"),
                "-e",
                f"@{workdir / 'extra.json'}",
            ],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        observed = json.loads(read_text(str(report)))
        for name, folder in (("first", first_dir), ("lua", lua_dir)):
            observed[name] = {
                domain: read_text(str(folder / f"{domain}.lua"))
                for domain in DOMAINS.values()
            }
        observed["web_svc"] = read_text(str(lua_dir / f"{WEB_SVC_DOMAIN}.lua"))
        observed["lua_files"] = sorted(path.name for path in lua_dir.glob("*.lua"))
        return observed


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestMatomoSelfServedFront(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = run_fronts()

    def _scripts(self, which: str, app: str) -> list[tuple[str, str]]:
        """Args:
            which: ``first`` for the Lua the front rendered, ``lua`` for the Lua after Matomo ran.
            app: the consumer whose vhost to read.

        Returns:
            the site id and code of every Matomo tracker script in that Lua.
        """
        return SCRIPT.findall(self.observed[which][DOMAINS[app]])

    def test_the_consumer_renders_its_own_script_with_its_private_vars(self) -> None:
        self.assertIn(
            f"const hiddenEntries = [{json.dumps(HIDDEN_ENTRY)}];",
            self.observed["lua"][DOMAINS[UNSITED]],
        )

    def test_matomo_gives_the_front_its_site_under_the_csp_of_its_render(
        self,
    ) -> None:
        allowed = self.observed["first_csp"][DOMAINS[UNSITED]]["script-src-elem"]
        scripts = self._scripts("lua", UNSITED)
        self.assertEqual([site for site, _ in scripts], ["8"])
        self.assertIn(scripts[0][1], allowed)

    def test_matomo_changes_nothing_but_the_site_id(self) -> None:
        first = self.observed["first"][DOMAINS[UNSITED]]
        self.assertEqual(
            self.observed["lua"][DOMAINS[UNSITED]],
            first.replace('data-matomo-site-id=""', 'data-matomo-site-id="8"').replace(
                "matomo.php?idsite=&", "matomo.php?idsite=8&"
            ),
        )
        self.assertEqual([site for site, _ in self._scripts("first", UNSITED)], [""])

    def test_only_the_front_without_a_site_is_recorded_with_its_vhosts(self) -> None:
        self.assertEqual(
            self.observed["recorded"],
            {
                UNSITED: {
                    "id": UNSITED,
                    "phase": "entered",
                    "domains": [DOMAINS[UNSITED]],
                }
            },
        )
        self.assertEqual(self.observed["left"], [])

    def test_the_web_svc_re_render_writes_the_consumers_own_site_id(self) -> None:
        self.assertNotIn(EARLIER_PLAY, self.observed["web_svc"])
        self.assertEqual(
            [site for site, _ in SCRIPT.findall(self.observed["web_svc"])],
            [SITE_IDS[WEB_SVC_DOMAIN]],
        )
        self.assertIn(
            f"matomo.php?idsite={SITE_IDS[WEB_SVC_DOMAIN]}&", self.observed["web_svc"]
        )
        self.assertEqual(
            self.observed["lua_files"],
            sorted(f"{domain}.lua" for domain in (*DOMAINS.values(), WEB_SVC_DOMAIN)),
        )

    def test_a_front_that_found_its_site_keeps_its_render(self) -> None:
        self.assertEqual([site for site, _ in self._scripts("first", SITED)], ["9"])
        self.assertEqual(
            self.observed["lua"][DOMAINS[SITED]],
            self.observed["first"][DOMAINS[SITED]],
        )


if __name__ == "__main__":
    unittest.main()
