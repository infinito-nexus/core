from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

ROLE_TASKS = Path("roles/sys-svc-certs/tasks")
ONCE_FLAG = Path("tasks/utils/once/flag.yml")
WILDCARD = "-d example -d *.example"

STUB_HTTPS = """---
- name: Record the webserver-https entry
  ansible.builtin.set_fact:
    https_entries: "{{ https_entries + 1 }}"
    run_once_sys_svc_webserver_https: true
"""

STUB_USERS_LOOKUP = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{"email": "admin@example", "secondary_email": ""}]
"""

STUB_CERT_CHECK = """from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={"domain": {"type": "str"}, "cert_base_path": {"type": "str"}}
    )
    module.exit_json(changed=False, exists=False)


main()
"""

FAKE_CERTBOT = """#!/bin/sh
printf '%s\\n' "$*" >> "$CERTBOT_LOG"
"""

PLAYBOOK = """---
- name: Enter sys-svc-certs once per arriving domain
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    https_entries: 0
    DOMAIN_PRIMARY: example
    CERTBOT_ACME_CHALLENGE_METHOD: webroot
    LETSENCRYPT_WEBROOT_PATH: /var/lib/letsencrypt
    LETSENCRYPT_LIVE_PATH: /etc/letsencrypt/live
    DUMMY: false
  tasks:
    - name: Request the certificates of every arriving domain
      ansible.builtin.include_role:
        name: sys-svc-certs
      loop: "{{ arriving_domains }}"
      loop_control:
        loop_var: arriving_domain
      vars:
        domain: "{{ arriving_domain }}"

    - name: Report the webserver-https entries
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: "{{ https_entries }}"
        mode: "0644"
"""


def _write(path: Path, body: str) -> None:
    """Args:
    path: the file to create, parents included.
    body: its text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def requested_certificates(
    flavor: str, arriving: list[str], overrides: dict[str, str] | None = None
) -> tuple[list[str], int]:
    """Args:
        flavor: the CERTBOT_FLAVOR of the run.
        arriving: the domains in the order sys-svc-certs is entered with them.
        overrides: role task files, keyed by their path under the role's
            tasks directory, that replace the real ones.

    Returns:
        the -d arguments of every certbot call in call order, and how often
        sys-svc-webserver-https was entered.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    overrides = overrides or {}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        tasks = PROJECT_ROOT / ROLE_TASKS
        for source in iter_project_files(extensions=(".yml",)):
            if not source.startswith(f"{tasks}{os.sep}"):
                continue
            rel = str(Path(source).relative_to(tasks))
            _write(workdir / ROLE_TASKS / rel, overrides.get(rel, read_text(source)))
        for rel, body in overrides.items():
            _write(workdir / ROLE_TASKS / rel, body)
        _write(workdir / ONCE_FLAG, read_text(str(PROJECT_ROOT / ONCE_FLAG)))
        _write(
            workdir / "roles/sys-svc-webserver-https" / ROLE_FILE_TASKS_MAIN, STUB_HTTPS
        )
        _write(workdir / "lookup/users.py", STUB_USERS_LOOKUP)
        _write(workdir / "library/cert_check_exists.py", STUB_CERT_CHECK)
        certbot = workdir / "bin/certbot"
        _write(certbot, FAKE_CERTBOT)
        certbot.chmod(0o755)
        _write(workdir / "play.yml", PLAYBOOK)
        log, report = workdir / "certbot.log", workdir / "report.txt"
        env = {
            **os.environ,
            "PATH": f"{workdir / 'bin'}:{os.environ['PATH']}",
            "CERTBOT_LOG": str(log),
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": str(workdir / "lookup"),
            "ANSIBLE_LIBRARY": str(workdir / "library"),
        }
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                str(workdir / "play.yml"),
                "-e",
                json.dumps(
                    {
                        "CERTBOT_FLAVOR": flavor,
                        "arriving_domains": arriving,
                        "report_out": str(report),
                    }
                ),
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
        calls = (
            [call.split() for call in read_text(str(log)).splitlines()]
            if log.exists()
            else []
        )
        requested = [
            " ".join(f"-d {args[i + 1]}" for i, arg in enumerate(args) if arg == "-d")
            for args in calls
        ]
        return requested, int(read_text(str(report)))


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestWildcardOnce(unittest.TestCase):
    def test_a_deep_first_domain_still_gets_the_wildcard(self) -> None:
        requested, _ = requested_certificates(
            "wildcard", ["deep.sub.example", "a.example", "b.example"]
        )
        self.assertEqual(requested, [WILDCARD, "-d deep.sub.example"])

    def test_a_direct_first_domain_gets_the_same_certificates(self) -> None:
        requested, _ = requested_certificates(
            "wildcard", ["a.example", "deep.sub.example"]
        )
        self.assertEqual(requested, [WILDCARD, "-d deep.sub.example"])

    def test_the_dedicated_flavor_requests_no_wildcard(self) -> None:
        requested, _ = requested_certificates(
            "dedicated", ["a.example", "deep.sub.example"]
        )
        self.assertEqual(requested, ["-d a.example", "-d deep.sub.example"])

    def test_the_host_part_enters_webserver_https_once(self) -> None:
        _, entries = requested_certificates("wildcard", ["a.example", "b.example"])
        self.assertEqual(entries, 1)


if __name__ == "__main__":
    unittest.main()
