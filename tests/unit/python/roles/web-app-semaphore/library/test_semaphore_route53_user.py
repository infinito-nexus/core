from __future__ import annotations

import contextlib
import io
import json
import unittest
import unittest.mock as mock

from ansible.module_utils.testing import patch_module_args

from utils import aws_api

from ._fake_aws import ADMIN, FakeAws, load

mod = load("semaphore_route53_user")

USER = "ws-4f1c2a3e-1b2c-4d5e-8f90-0123456789ab"
NAME = "records"
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ReadChange",
            "Effect": "Allow",
            "Action": "route53:GetChange",
            "Resource": "arn:aws:route53:::change/*",
        }
    ],
}
FIRST = ["CreateUser", "PutUserPolicy", "CreateAccessKey"]


def held_policies(fake):
    return {n: json.loads(d) for n, d in fake.users[USER]["policies"].items()}


def apply(held, check_mode=False):
    session = mod.Session(ADMIN, check_mode)
    return session, mod.present(session, USER, NAME, POLICY, held)


def idempotency_findings(fake):
    """Args:
        fake: a fake AWS without the user.

    Returns:
        One message per way two applies of a new workspace leave other than
        one user with exactly the rendered policy and one key, or the second
        apply writes or mints.
    """
    findings = []
    session, first = apply("")
    if session.changes != FIRST or not first["minted"]:
        findings.append(f"the first apply ran {session.changes}")
    session, second = apply(first["access_key_id"])
    if session.changes:
        findings.append(f"the second apply ran {session.changes}")
    if second["minted"] or second["secret_access_key"] is not None:
        findings.append("the second apply minted a key")
    if list(fake.users[USER]["keys"]) != [first["access_key_id"]]:
        findings.append(f"the user holds {sorted(fake.users[USER]['keys'])}")
    if held_policies(fake) != {NAME: POLICY}:
        findings.append(f"the user holds the policies {sorted(held_policies(fake))}")
    return findings


class FakeTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeAws()
        patcher = mock.patch.object(aws_api, "send", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, keys, policies=None):
        self.fake.users[USER] = {
            "policies": policies
            if policies is not None
            else {NAME: json.dumps(POLICY)},
            "keys": dict(keys),
            "attached": False,
        }

    def tearDown(self):
        self.assertEqual(self.fake.leaks, [])


class TestApply(FakeTestCase):
    def test_a_first_apply_creates_the_user_its_exact_policy_and_one_key(self):
        session, result = apply("")
        self.assertEqual(session.changes, FIRST)
        self.assertEqual(held_policies(self.fake), {NAME: POLICY})
        self.assertEqual(
            self.fake.users[USER]["keys"], {result["access_key_id"]: "Active"}
        )
        self.assertEqual(result["secret_access_key"], "minted-secret-1")
        self.assertTrue(result["minted"])

    def test_a_second_apply_keeps_the_user_and_its_key_and_reports_unchanged(self):
        self.assertEqual(idempotency_findings(self.fake), [])
        self.assertEqual(self.fake.minted, 1)

    def test_negative_control_a_key_never_taken_as_valid_fails(self):
        with mock.patch.object(mod, "ACTIVE", "Enabled"):
            findings = idempotency_findings(self.fake)
        self.assertIn("the second apply minted a key", findings)

    def test_negative_control_a_policy_written_on_every_apply_fails(self):
        def always_put(session, user, name, policy):
            session.write(
                "PutUserPolicy",
                UserName=user,
                PolicyName=name,
                PolicyDocument=json.dumps(policy),
            )

        with mock.patch.object(mod, "_policy", always_put):
            findings = idempotency_findings(self.fake)
        self.assertEqual(findings, ["the second apply ran ['PutUserPolicy']"])

    def test_apply_deletes_a_stray_key_and_keeps_the_held_one(self):
        self.seed({"AKIAHELD": "Active", "AKIASTRAY": "Active"})
        session, result = apply("AKIAHELD")
        self.assertEqual(session.changes, ["DeleteAccessKey"])
        self.assertEqual(self.fake.users[USER]["keys"], {"AKIAHELD": "Active"})
        self.assertEqual(
            result,
            {"minted": False, "access_key_id": "AKIAHELD", "secret_access_key": None},
        )

    def test_apply_replaces_a_key_the_record_does_not_hold(self):
        self.seed({"AKIALOST": "Active"})
        session, result = apply("")
        self.assertEqual(session.changes, ["DeleteAccessKey", "CreateAccessKey"])
        self.assertEqual(
            self.fake.users[USER]["keys"], {result["access_key_id"]: "Active"}
        )

    def test_apply_replaces_an_inactive_or_deleted_held_key(self):
        for keys in ({"AKIAHELD": "Inactive"}, {}):
            with self.subTest(keys=keys):
                self.seed(keys)
                session, result = apply("AKIAHELD")
                self.assertEqual(session.changes[-1], "CreateAccessKey")
                self.assertTrue(result["minted"])
                self.assertEqual(
                    list(self.fake.users[USER]["keys"]), [result["access_key_id"]]
                )

    def test_apply_restores_the_exact_policy_and_drops_any_other(self):
        widened = json.loads(json.dumps(POLICY))
        widened["Statement"][0]["Action"] = "route53:*"
        self.seed(
            {"AKIAHELD": "Active"},
            {NAME: json.dumps(widened), "extra": json.dumps(POLICY)},
        )
        session, _ = apply("AKIAHELD")
        self.assertEqual(session.changes, ["DeleteUserPolicy", "PutUserPolicy"])
        self.assertEqual(held_policies(self.fake), {NAME: POLICY})

    def test_check_mode_writes_nothing(self):
        session, result = apply("", check_mode=True)
        self.assertEqual(session.changes, ["CreateUser"])
        self.assertEqual(self.fake.writes(), [])
        self.assertIsNone(result["secret_access_key"])
        self.seed({"AKIAHELD": "Inactive"})
        session, _ = apply("AKIAHELD", check_mode=True)
        self.assertEqual(session.changes, ["DeleteAccessKey", "CreateAccessKey"])
        self.assertEqual(self.fake.writes(), [])


class TestDestroy(FakeTestCase):
    def test_destroy_removes_the_keys_the_policies_and_the_user(self):
        self.seed({"AKIAONE": "Active", "AKIATWO": "Inactive"}, {NAME: "{}", "x": "{}"})
        session = mod.Session(ADMIN, False)
        mod.absent(session, USER)
        self.assertEqual(
            session.changes,
            [
                "DeleteAccessKey",
                "DeleteAccessKey",
                "DeleteUserPolicy",
                "DeleteUserPolicy",
                "DeleteUser",
            ],
        )
        self.assertNotIn(USER, self.fake.users)
        again = mod.Session(ADMIN, False)
        mod.absent(again, USER)
        self.assertEqual(again.changes, [])

    def test_destroy_refuses_a_user_it_cannot_empty(self):
        self.seed({})
        self.fake.users[USER]["attached"] = True
        with self.assertRaises(aws_api.AwsError) as caught:
            mod.absent(mod.Session(ADMIN, False), USER)
        self.assertEqual(caught.exception.code, "DeleteConflict")

    def test_negative_control_a_destroy_that_keeps_the_keys_fails(self):
        self.seed({"AKIAONE": "Active"})
        with (
            mock.patch.object(mod, "_members", lambda s, a, u, f: []),
            self.assertRaises(aws_api.AwsError) as caught,
        ):
            mod.absent(mod.Session(ADMIN, False), USER)
        self.assertEqual(caught.exception.code, "DeleteConflict")
        self.assertIn(USER, self.fake.users)


def run_main(args):
    buffer = io.StringIO()
    with (
        patch_module_args(args),
        contextlib.redirect_stdout(buffer),
        contextlib.suppress(SystemExit),
    ):
        mod.main()
    return buffer.getvalue()


ARGS = {
    "user": USER,
    "admin_access_key_id": ADMIN["access_key_id"],
    "admin_secret_access_key": ADMIN["secret_access_key"],
}


class TestModule(FakeTestCase):
    def test_present_returns_the_minted_key_and_never_the_admin_secret(self):
        args = {
            **ARGS,
            "state": "present",
            "policy_name": NAME,
            "policy": POLICY,
            "held_access_key_id": "",
        }
        output = run_main(args)
        result = json.loads(output)
        self.assertTrue(result["changed"])
        self.assertEqual(result["secret_access_key"], "minted-secret-1")
        self.assertNotIn(ADMIN["secret_access_key"], output)
        result = json.loads(
            run_main({**args, "held_access_key_id": result["access_key_id"]})
        )
        self.assertFalse(result["changed"])
        self.assertIsNone(result["secret_access_key"])

    def test_present_needs_the_policy_and_the_held_key(self):
        result = json.loads(run_main({**ARGS, "state": "present"}))
        self.assertTrue(result["failed"])
        self.assertIn("policy", result["msg"])

    def test_a_refusal_names_the_aws_error_and_never_the_admin_secret(self):
        self.fake.denied.add("GetUser")
        output = run_main({**ARGS, "state": "absent"})
        result = json.loads(output)
        self.assertTrue(result["failed"])
        self.assertIn("AccessDenied", result["msg"])
        self.assertIn(USER, result["msg"])
        self.assertNotIn(ADMIN["secret_access_key"], output)


if __name__ == "__main__":
    unittest.main()
