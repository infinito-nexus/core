"""Another role's directory lookup must run kcadm in the Keycloak container.

The stack loader enters every role with ``application_id`` as an include param,
which outranks the ``application_id`` that ``web-app-keycloak/vars/main.yml``
declares. When Mastodon includes ``utils/directory_users.yml``, a login that
derives its container from ``application_id`` resolves Mastodon's container and
kcadm is not found there (CI run 43777013536, Fediwall_2 and Nextcloud_5).

Each mode runs real Ansible on the real ``web-app-keycloak`` role (helper,
login, reader, vars and filters), the real ``sys-svc-compose`` resolver and
swarm converge script, and the real ``container_address``,
``container_service`` and ``path_absolute`` lookups, under Mastodon's id. Only
the ``applications`` lookup is reduced to the two roles' real service names,
and a fake ``container`` binary records which container or swarm service every
call names.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

KEYCLOAK = "web-app-keycloak"
CALLER = "web-app-mastodon"
PROBE_ROLE = "probe-caller"
LINKED_ROLES = (KEYCLOAK, "sys-svc-compose")
LINKED_LOOKUPS = ("container_address", "container_service", "path_absolute")
LINKED_FILTERS = (Path("get") / "entity_name.py",)
PLAYBOOK_TIMEOUT = 300
MODES = ("compose", "swarm")
VERBS = {
    "compose": {"inspect", "exec"},
    "swarm": {"service", "ps", "inspect", "exec"},
}
ADMIN = {
    "id": "sub-admin",
    "username": "administrator",
    "email": "admin@example.invalid",
    "emailVerified": True,
}

APPLICATIONS_LOOKUP = """from ansible.plugins.lookup import LookupBase

APPLICATIONS = {applications}


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [APPLICATIONS[terms[0]]] if terms else [APPLICATIONS]
"""

FAKE_CONTAINER = """#!{python}
import json
import sys

CID = "cid-"
LABEL = "label=com.docker.swarm.service.name="
args = sys.argv[1:]
verb, rest = (args[0], args[1:]) if args else ("", [])
joined = " ".join(rest)
target = ""
if verb == "inspect":
    target = rest[-1]
    print("healthy" if "Health" in joined else "true")
elif verb == "service":
    target = rest[1]
    if rest[0] == "inspect":
        print("completed")
    elif "Node" in joined:
        print("localhost")
    elif "CurrentState" in joined:
        print("Running 5 seconds ago")
elif verb == "ps":
    target = next(arg[len(LABEL):] for arg in rest if arg.startswith(LABEL))
    print(CID + target)
elif verb == "exec":
    index = 0
    while rest[index].startswith("-"):
        index += 2 if rest[index] in ("-e", "-u", "-w") else 1
    target = rest[index]
    if "get" in rest and "users" in rest:
        print(json.dumps([{admin}]))
with open({log!r}, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{
        "verb": verb,
        "target": target.removeprefix(CID),
        "login": "config credentials" in joined,
        "read": "get" in rest and "users" in rest,
    }}) + "\\n")
"""

PLAYBOOK = """---
- name: Enter a caller the way the stack loader does
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    DEPLOYMENT_MODE: {mode}
    IS_COMPOSE_MODE: {compose}
    IS_SWARM_MODE: {swarm}
    IS_STACK_HOST: true
    STACK_HOST: localhost
    MASK_CREDENTIALS_IN_LOGS: false
    OIDC:
      CLIENT:
        REALM: probe
    sso_by_application:
      {caller}: true
  tasks:
    - name: Run the caller with its id as include param
      ansible.builtin.include_role:
        name: {probe}
      vars:
        application_id: {caller}
"""

CALLER_TASKS = dump_yaml_str(
    [
        {
            "name": "Bind the caller's accounts to their Keycloak users",
            "when": "sso_by_application[application_id]",
            "block": [
                {
                    "name": "Read the Keycloak directory users",
                    "ansible.builtin.include_role": {
                        "name": KEYCLOAK,
                        "tasks_from": "utils/directory_users.yml",
                    },
                    "vars": {"keycloak_directory_usernames": [ADMIN["username"]]},
                },
            ],
        }
    ]
)


def _service_name(role: str, key: str) -> str:
    """Args:
        role: the role whose ``meta/services.yml`` declares the service.
        key: the service key.

    Returns:
        The service's real container name.
    """
    services = load_yaml_any(
        str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    )
    return services[key]["name"]


def _keycloak_target(mode: str) -> str:
    """Args:
        mode: the deployment mode the play ran in.

    Returns:
        The name every call must target: the compose container or the swarm service.
    """
    return (
        "keycloak_keycloak" if mode == "swarm" else _service_name(KEYCLOAK, "keycloak")
    )


def _build(workdir: Path, mode: str) -> dict[str, str]:
    """Lay out the roles, plugins, fake binary and play in ``workdir``.

    Args:
        workdir: an empty directory to build the fixture in.
        mode: the deployment mode the play runs in.

    Returns:
        The environment ansible-playbook runs with.
    """
    for role in LINKED_ROLES:
        target = workdir / "roles" / role
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(PROJECT_ROOT / "roles" / role, target_is_directory=True)
    lookups = workdir / "lookup_plugins"
    lookups.mkdir()
    for name in LINKED_LOOKUPS:
        (lookups / f"{name}.py").symlink_to(
            PROJECT_ROOT / "plugins/lookup" / f"{name}.py"
        )
    applications = {
        KEYCLOAK: {
            "services": {"keycloak": {"name": _service_name(KEYCLOAK, "keycloak")}}
        },
        CALLER: {"services": {"mastodon": {"name": _service_name(CALLER, "mastodon")}}},
    }
    (lookups / "applications.py").write_text(
        APPLICATIONS_LOOKUP.format(applications=repr(applications))
    )
    filters = workdir / "filter_plugins"
    filters.mkdir()
    for relative in LINKED_FILTERS:
        (filters / relative.name).symlink_to(PROJECT_ROOT / "plugins/filter" / relative)
    caller = workdir / "roles" / PROBE_ROLE
    for relative, body in (
        (ROLE_FILE_VARS_MAIN, f"---\napplication_id: {CALLER}\n"),
        (ROLE_FILE_TASKS_MAIN, CALLER_TASKS),
    ):
        (caller / relative).parent.mkdir(parents=True, exist_ok=True)
        (caller / relative).write_text(body)
    binary = workdir / "bin" / "container"
    binary.parent.mkdir()
    binary.write_text(
        FAKE_CONTAINER.format(
            python=sys.executable, log=str(workdir / "container.log"), admin=repr(ADMIN)
        )
    )
    binary.chmod(0o755)
    (workdir / "ansible.cfg").write_text(
        "[defaults]\n"
        f"roles_path = {workdir / 'roles'}\n"
        f"lookup_plugins = {lookups}\n"
        f"filter_plugins = {filters}\n"
        "retry_files_enabled = False\n"
    )
    (workdir / "play.yml").write_text(
        PLAYBOOK.format(
            mode=mode,
            compose=mode == "compose",
            swarm=mode == "swarm",
            caller=CALLER,
            probe=PROBE_ROLE,
        )
    )
    return {
        **os.environ,
        "ANSIBLE_CONFIG": str(workdir / "ansible.cfg"),
        "PATH": f"{binary.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(PROJECT_ROOT), os.environ.get("PYTHONPATH", "")))
        ),
    }


def _run(workdir: Path, mode: str) -> dict:
    """Run the play once and collect what the fake binary saw.

    Args:
        workdir: an empty directory to build the fixture in.
        mode: the deployment mode the play runs in.

    Returns:
        ``rc``, the joined ``output`` and the recorded ``calls``.
    """
    env = _build(workdir, mode)
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            str(workdir / "play.yml"),
        ],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=PLAYBOOK_TIMEOUT,
    )
    log = workdir / "container.log"
    return {
        "rc": result.returncode,
        "output": result.stdout + result.stderr,
        "calls": [json.loads(line) for line in read_text(str(log)).splitlines()]
        if log.exists()
        else [],
    }


class TestDirectoryUsersReachesKeycloak(unittest.TestCase):
    runs: ClassVar[dict[str, dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        """One play per mode answers every case, so each runs once rather than per case."""
        if not shutil.which("ansible-playbook"):
            return
        for mode in MODES:
            with tempfile.TemporaryDirectory() as tmp:
                cls.runs[mode] = _run(Path(tmp), mode)

    def setUp(self) -> None:
        if not self.runs:
            self.skipTest("ansible-playbook not found")

    def test_every_call_names_keycloak_in_each_mode(self) -> None:
        for mode in MODES:
            run = self.runs[mode]
            with self.subTest(mode=mode):
                self.assertEqual(run["rc"], 0, run["output"])
                self.assertEqual(
                    {call["verb"] for call in run["calls"]}, VERBS[mode], run["output"]
                )
                self.assertEqual(
                    {call["target"] for call in run["calls"]}, {_keycloak_target(mode)}
                )

    def test_the_login_and_the_directory_read_exec_in_keycloak(self) -> None:
        for mode in MODES:
            execs = [
                call for call in self.runs[mode]["calls"] if call["verb"] == "exec"
            ]
            target = _keycloak_target(mode)
            with self.subTest(mode=mode):
                self.assertTrue(
                    any(c["login"] and c["target"] == target for c in execs)
                )
                self.assertTrue(any(c["read"] and c["target"] == target for c in execs))


if __name__ == "__main__":
    unittest.main()
