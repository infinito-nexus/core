from __future__ import annotations

import json
import unittest

from utils.cache.files import read_text

from ._fake_pve import PERL, SCRIPTS, run_script

SCRIPT = read_text(str(SCRIPTS / "rbac.pl"))
REALM = "keycloak"
GROUP = "web-app-proxmox-administrator"
ALICE = {"username": "alice", "email": "alice@example.org", "name": "Alice"}


def _env(members: list[dict]) -> dict[str, str]:
    return {
        "PROXMOX_REALM": REALM,
        "PROXMOX_GROUP": GROUP,
        "PROXMOX_RBAC_ADMINISTRATORS": json.dumps(members),
    }


def _state(
    holders: list[str], users: list[str], other_groups: dict | None = None
) -> dict:
    groups = {GROUP: {"users": dict.fromkeys(holders, 1)}}
    for name, members in (other_groups or {}).items():
        groups[name] = {"users": dict.fromkeys(members, 1)}
    return {"user.cfg": {"groups": groups, "users": {userid: {} for userid in users}}}


@unittest.skipUnless(PERL, "perl is not installed")
class TestRbacScript(unittest.TestCase):
    def test_a_new_member_is_created_inside_the_group(self):
        run = run_script(SCRIPT, _state([], []), _env([ALICE]))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::User->create_user",
                    "param": {
                        "userid": f"alice@{REALM}",
                        "enable": 1,
                        "groups": GROUP,
                        "email": ALICE["email"],
                    },
                }
            ],
        )
        self.assertIn("[CHANGED]", run.stdout)

    def test_an_existing_account_is_appended_to_the_group(self):
        run = run_script(SCRIPT, _state([], [f"alice@{REALM}"]), _env([ALICE]))
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::User->update_user",
                    "param": {"userid": f"alice@{REALM}", "groups": GROUP, "append": 1},
                }
            ],
        )

    def test_converged_membership_writes_nothing(self):
        state = _state([f"alice@{REALM}"], [f"alice@{REALM}"])
        run = run_script(SCRIPT, state, _env([ALICE]))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.calls, [])
        self.assertNotIn("[CHANGED]", run.stdout)

    def test_negative_control_a_former_member_is_demoted_and_keeps_other_groups(self):
        state = _state(
            [f"alice@{REALM}", f"bob@{REALM}"],
            [f"alice@{REALM}", f"bob@{REALM}"],
            {"ops": [f"bob@{REALM}"], "dev": []},
        )
        run = run_script(SCRIPT, state, _env([ALICE]))
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::User->update_user",
                    "param": {"userid": f"bob@{REALM}", "groups": "ops"},
                }
            ],
        )
        self.assertIn(f"bob@{REALM} removed from group {GROUP}", run.stdout)

    def test_an_account_of_another_realm_is_demoted_too(self):
        state = _state(["root@pam"], ["root@pam"])
        run = run_script(SCRIPT, state, _env([]))
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::User->update_user",
                    "param": {"userid": "root@pam", "groups": ""},
                }
            ],
        )

    def test_a_member_without_username_is_skipped(self):
        run = run_script(
            SCRIPT, _state([], []), _env([{"username": "", "email": "x@example.org"}])
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.calls, [])

    def test_a_missing_group_is_refused(self):
        run = run_script(
            SCRIPT, {"user.cfg": {"groups": {}, "users": {}}}, _env([ALICE])
        )
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("[FAIL]", run.stderr)
        self.assertEqual(run.calls, [])

    def test_a_missing_member_list_is_refused(self):
        env = _env([ALICE])
        env["PROXMOX_RBAC_ADMINISTRATORS"] = ""
        run = run_script(SCRIPT, _state([], []), env)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.calls, [])


if __name__ == "__main__":
    unittest.main()
