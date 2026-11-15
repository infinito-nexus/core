from __future__ import annotations

import base64
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._fake_pve import PERL, ROLE, SCRIPTS, run_script

SCRIPT = read_text(str(SCRIPTS / "access.pl"))
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
TASK = next(
    task
    for task in load_yaml_any(
        str(ROLE / "tasks" / "01_access.yml"), default_if_missing=[]
    )
    if "Converge the OpenID realm" in task.get("name", "")
)

SECRET = "s3cr3t-Value_42"
REALM = "keycloak"
GROUP = "web-app-proxmox-administrator"
ROLE_NAME = "Administrator"
CONFIG = {
    key: f"fake-{key}" if "{{" in str(value) else value
    for key, value in VARS["PROXMOX_REALM_CONFIG"].items()
}
GRANTED = {"acl_root": {"groups": {GROUP: {ROLE_NAME: 1}}}}


def _env(secret: str = SECRET, **overrides: str) -> dict[str, str]:
    env = {
        "PROXMOX_REALM": REALM,
        "PROXMOX_REALM_CONFIG": json.dumps(CONFIG),
        "PROXMOX_REALM_CLIENT_SECRET_B64": base64.b64encode(secret.encode()).decode(),
        "PROXMOX_GROUP": GROUP,
        "PROXMOX_GROUP_COMMENT": "members",
        "PROXMOX_ROLE": ROLE_NAME,
    }
    env.update(overrides)
    return env


def _state(
    realm: dict | None = None, group: dict | None = None, acl: dict | None = None
) -> dict:
    return {
        "domains.cfg": {"ids": {REALM: realm} if realm else {}},
        "user.cfg": {"groups": {GROUP: group} if group else {}, **(acl or {})},
    }


def _converged(**realm_overrides) -> dict:
    return _state(
        {"type": "openid", **CONFIG, "client-key": SECRET, **realm_overrides},
        {"comment": "members"},
        GRANTED,
    )


def _leaks(run, secret: str = SECRET) -> bool:
    encoded = base64.b64encode(secret.encode()).decode()
    return any(needle in run.stdout + run.stderr for needle in (secret, encoded))


@unittest.skipUnless(PERL, "perl is not installed")
class TestAccessScript(unittest.TestCase):
    def test_first_run_creates_realm_group_and_grant(self):
        run = run_script(SCRIPT, _state(), _env())
        self.assertEqual(run.returncode, 0, run.stderr)
        methods = [call["method"] for call in run.calls]
        self.assertEqual(
            methods,
            [
                "PVE::API2::Domains->create",
                "PVE::API2::Group->create_group",
                "PVE::API2::ACL->update_acl",
            ],
        )
        realm = run.calls[0]["param"]
        self.assertEqual(realm["realm"], REALM)
        self.assertEqual(realm["type"], "openid")
        self.assertEqual(realm["client-key"], SECRET)
        for key, value in CONFIG.items():
            self.assertEqual(realm[key], value, key)
        self.assertEqual(
            run.calls[2]["param"],
            {"path": "/", "groups": GROUP, "roles": ROLE_NAME, "propagate": 1},
        )
        self.assertEqual(run.stdout.count("[CHANGED]"), 3)

    def test_converged_state_writes_nothing(self):
        run = run_script(SCRIPT, _converged(), _env())
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.calls, [])
        self.assertNotIn("[CHANGED]", run.stdout)

    def test_negative_control_a_drifted_option_is_rewritten_alone(self):
        run = run_script(SCRIPT, _converged(**{"issuer-url": "https://old"}), _env())
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::Domains->update",
                    "param": {"realm": REALM, "issuer-url": CONFIG["issuer-url"]},
                }
            ],
        )

    def test_a_rotated_secret_is_written_but_never_printed(self):
        run = run_script(SCRIPT, _converged(), _env(secret="rotated-Secret_7"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.calls[0]["param"], {"realm": REALM, "client-key": "rotated-Secret_7"}
        )
        self.assertIn("client-key", run.stdout)
        self.assertFalse(_leaks(run, "rotated-Secret_7"))
        self.assertFalse(_leaks(run_script(SCRIPT, _state(), _env())))

    def test_negative_control_the_leak_check_catches_a_printed_secret(self):
        mutant = SCRIPT.replace(
            'print "[CHANGED] realm $realm created\\n";',
            "print \"[CHANGED] realm $realm created $desired->{'client-key'}\\n\";",
        )
        self.assertNotEqual(mutant, SCRIPT)
        self.assertTrue(_leaks(run_script(mutant, _state(), _env())))

    def test_an_empty_secret_is_refused(self):
        for env in (_env(secret=""), _env(PROXMOX_REALM_CLIENT_SECRET_B64="!!!!")):
            run = run_script(SCRIPT, _state(), env)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("[FAIL]", run.stderr)
            self.assertEqual(run.calls, [])

    def test_a_different_username_claim_is_refused(self):
        run = run_script(SCRIPT, _converged(**{"username-claim": "sub"}), _env())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("pveum realm delete keycloak", run.stderr)
        self.assertEqual(run.calls, [])

    def test_a_realm_of_another_type_is_refused(self):
        run = run_script(SCRIPT, _converged(type="pam"), _env())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("[FAIL]", run.stderr)
        self.assertEqual(run.calls, [])

    def test_a_missing_grant_is_added_to_a_converged_realm(self):
        state = _converged()
        state["user.cfg"].pop("acl_root")
        run = run_script(SCRIPT, state, _env())
        self.assertEqual(
            [call["method"] for call in run.calls], ["PVE::API2::ACL->update_acl"]
        )


def _fake_container(root: Path) -> Path:
    tool = root / "container"
    tool.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" > "$OUT/argv"\n'
        'printf \'%s\' "$PROXMOX_REALM_CLIENT_SECRET_B64" > "$OUT/env"\n'
        'cat > "$OUT/stdin"\n',
        encoding="utf-8",
    )
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def _run_cmd(
    cmd: str, stdin: str
) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_container(root)
        result = subprocess.run(
            ["sh", "-c", cmd],
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": f"{root}:{os.environ['PATH']}", "OUT": str(root)},
        )
        seen = {
            name: (root / name).read_text()  # nocheck: cache-read tempdir fixture
            if (root / name).exists()
            else ""
            for name in ("argv", "env", "stdin")
        }
    return result, seen


class TestSecretTransport(unittest.TestCase):
    CMD = TASK["ansible.builtin.shell"]["cmd"]
    STDIN = TASK["ansible.builtin.shell"]["stdin"]

    EXEC = "{{ (PROXMOX_GUEST_EXEC + ['perl', '-']) | map('quote') | join(' ') }}"

    def _rendered(self, cmd: str | None = None, guest: str = "") -> str:
        text = (cmd or self.CMD).replace(self.EXEC, f"{guest} perl -".strip())
        return re.sub(r"\{\{.*?\}\}", "pve-cid", text)

    def test_the_secret_is_templated_only_into_stdin(self):
        self.assertEqual(
            re.findall(r"\{\{.*?\}\}", self.CMD),
            ["{{ PROXMOX_LOCAL_CID | quote }}", self.EXEC],
        )
        self.assertEqual(
            self.STDIN.splitlines(),
            [
                "{{ PROXMOX_OIDC_CLIENT_SECRET | b64encode }}",
                "{{ lookup('file', 'perl/access.pl') }}",
            ],
        )
        for value in TASK["environment"].values():
            self.assertNotIn("SECRET", value)
        self.assertNotIn("client-key", VARS["PROXMOX_REALM_CONFIG"])
        self.assertEqual(TASK["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")

    def test_the_secret_reaches_the_container_env_but_no_argv(self):
        encoded = base64.b64encode(SECRET.encode()).decode()
        result, seen = _run_cmd(self._rendered(), f"{encoded}\n{SCRIPT}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = seen["argv"].splitlines()
        self.assertEqual(argv[:2], ["exec", "-i"])
        self.assertEqual(argv[-3:], ["pve-cid", "perl", "-"])
        self.assertIn("PROXMOX_REALM_CLIENT_SECRET_B64", argv)
        self.assertNotIn(encoded, seen["argv"])
        self.assertNotIn(SECRET, seen["argv"])
        self.assertEqual(seen["env"], encoded)
        self.assertEqual(seen["stdin"], f"{SCRIPT}\n")

    def test_the_vm_flavor_runs_the_script_through_the_guest_channel(self):
        encoded = base64.b64encode(SECRET.encode()).decode()
        result, seen = _run_cmd(
            self._rendered(guest="pve-guest"), f"{encoded}\n{SCRIPT}\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = seen["argv"].splitlines()
        self.assertEqual(argv[-4:], ["pve-cid", "pve-guest", "perl", "-"])
        self.assertNotIn(encoded, seen["argv"])
        self.assertEqual(seen["env"], encoded)

    def test_negative_control_a_secret_passed_by_value_shows_on_the_argv(self):
        encoded = base64.b64encode(SECRET.encode()).decode()
        mutant = self.CMD.replace(
            "-e PROXMOX_REALM_CLIENT_SECRET_B64",
            '-e PROXMOX_REALM_CLIENT_SECRET_B64="$PROXMOX_REALM_CLIENT_SECRET_B64"',
        )
        self.assertNotEqual(mutant, self.CMD)
        _, seen = _run_cmd(self._rendered(mutant), f"{encoded}\n{SCRIPT}\n")
        self.assertIn(encoded, seen["argv"])

    def test_no_stdin_fails_before_the_container_is_reached(self):
        result, seen = _run_cmd(self._rendered(), "")
        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL]", result.stderr)
        self.assertEqual(seen["argv"], "")


if __name__ == "__main__":
    unittest.main()
