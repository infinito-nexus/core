import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock as mock
import urllib.parse

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import email_verified as m

LDAP_NAME = "example.com"
LDAP_ID = "ldap-1"


class FakeKeycloak:
    def __init__(self):
        self.users = {}
        self.puts = []
        self.failing = set()
        self.components = [
            {"id": LDAP_ID, "name": LDAP_NAME, "providerId": "ldap"},
            {"id": "kerberos-1", "name": LDAP_NAME, "providerId": "kerberos"},
        ]

    def add_user(self, username, verified, **extra):
        user_id = f"u-{len(self.users) + 1}"
        self.users[user_id] = {
            "id": user_id,
            "username": username,
            "emailVerified": verified,
            **extra,
        }
        return user_id

    def _list(self, params):
        first, size = int(params["first"][0]), int(params["max"][0])
        return [dict(u) for u in list(self.users.values())[first : first + size]]

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        params = urllib.parse.parse_qs(query)
        if method == "GET" and route == "components":
            assert params["type"] == [m.USER_STORAGE], params
            return [c for c in self.components if c["name"] == params["name"][0]], ""
        if method == "GET" and route == "users" and "username" not in params:
            return self._list(params), ""
        if method == "GET" and route == "users":
            wanted = params["username"][0]
            if wanted in self.failing:
                raise m.KeycloakError(f"GET {path}: HTTP 500")
            return [
                dict(u) for u in self.users.values() if wanted.lower() in u["username"]
            ], ""
        if method == "GET" and route.startswith("users/"):
            return dict(self.users[route.split("/")[1]]), ""
        if method == "PUT" and route.startswith("users/"):
            user_id = route.split("/")[1]
            self.puts.append(user_id)
            self.users[user_id] = dict(payload)
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")


class TestVerify(unittest.TestCase):
    def test_an_unverified_user_holding_its_inventory_address_is_updated(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="biber@example.org", firstName="B")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "updated")
        self.assertIs(kc.users[user_id]["emailVerified"], True)
        self.assertEqual(kc.users[user_id]["email"], "biber@example.org")
        self.assertEqual(kc.users[user_id]["firstName"], "B")

    def test_the_inventory_address_matches_case_insensitively(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False, email="Biber@Example.org")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "updated")

    def test_an_address_the_user_set_himself_stays_unverified(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="claimed@example.net")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "foreign")
        self.assertIs(kc.users[user_id]["emailVerified"], False)
        self.assertEqual(kc.puts, [])

    def test_a_user_without_inventory_address_is_skipped(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="claimed@example.net")
        self.assertEqual(m.verify(kc, "biber", ""), "none")
        self.assertIs(kc.users[user_id]["emailVerified"], False)
        self.assertEqual(kc.puts, [])

    def test_a_mailbox_user_without_secondary_address_is_skipped(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False)
        self.assertEqual(m.verify(kc, "biber", ""), "none")
        self.assertEqual(kc.puts, [])

    def test_a_user_holding_another_address_is_never_marked_verified(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="erpnext-api-bot@example.org")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "foreign")
        self.assertIs(kc.users[user_id]["emailVerified"], False)
        self.assertEqual(kc.puts, [])

    def test_a_user_without_an_address_is_never_marked_verified(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False)
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "foreign")
        self.assertEqual(kc.puts, [])

    def test_the_addresses_compare_case_insensitively(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False, email="biber@example.org")
        self.assertEqual(m.verify(kc, "biber", "Biber@Example.org"), "updated")

    def test_a_verified_user_holding_its_inventory_address_is_left_alone(self):
        kc = FakeKeycloak()
        kc.add_user("biber", True, email="biber@example.org")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "unchanged")
        self.assertEqual(kc.puts, [])

    def test_an_absent_user_is_reported_missing(self):
        kc = FakeKeycloak()
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "missing")
        self.assertEqual(kc.puts, [])

    def test_only_the_exact_username_is_touched(self):
        kc = FakeKeycloak()
        other = kc.add_user("contact2", False, email="contact@example.org")
        target = kc.add_user("contact", False, email="contact@example.org")
        self.assertEqual(m.verify(kc, "Contact", "contact@example.org"), "updated")
        self.assertEqual(kc.puts, [target])
        self.assertIs(kc.users[other]["emailVerified"], False)


def run_main(kc, extra_env):
    """Run the script's ``main`` against *kc* and return its exit code and stdout lines.

    Args:
        kc: the fake client.
        extra_env: the selection's environment, ``EMAILS`` or ``FEDERATION``.
    """
    out = io.StringIO()
    env = {"KC_URL": "http://kc", "KC_PID": "1", "KC_REALM": "r", **extra_env}
    with (
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch.object(m, "Keycloak", lambda *args: kc),
        mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = m.main()
    return code, out.getvalue().splitlines()


class TestFederation(unittest.TestCase):
    def setUp(self):
        self.kc = FakeKeycloak()
        self.directory = self.kc.add_user(
            "biber", False, email="biber@example.org", federationLink=LDAP_ID
        )
        self.verified = self.kc.add_user(
            "administrator",
            True,
            email="administrator@example.org",
            federationLink=LDAP_ID,
        )
        self.blank = self.kc.add_user(
            "castor", False, email=" ", federationLink=LDAP_ID
        )
        self.local = self.kc.add_user("mapache", False, email="mapache@example.net")
        self.foreign = self.kc.add_user(
            "zorro", False, email="zorro@example.net", federationLink="other-ldap"
        )

    def federate(self):
        return run_main(self.kc, {"FEDERATION": LDAP_NAME})

    def test_a_directory_user_gets_verified(self):
        code, lines = self.federate()
        self.assertEqual(code, 0)
        self.assertIs(self.kc.users[self.directory]["emailVerified"], True)
        self.assertEqual(self.kc.users[self.directory]["email"], "biber@example.org")
        self.assertIn("updated biber", lines)
        self.assertEqual(
            lines[-1],
            "summary updated=1 unchanged=1 none=1 missing=0 foreign=0 failed=0",
        )

    def test_a_local_user_stays_unverified(self):
        self.federate()
        self.assertIs(self.kc.users[self.local]["emailVerified"], False)
        self.assertIs(self.kc.users[self.foreign]["emailVerified"], False)
        self.assertIs(self.kc.users[self.blank]["emailVerified"], False)
        self.assertEqual(self.kc.puts, [self.directory])

    def test_a_second_run_reports_unchanged(self):
        self.federate()
        code, lines = self.federate()
        self.assertEqual(code, 0)
        self.assertEqual(self.kc.puts, [self.directory])
        self.assertEqual(
            lines[-1],
            "summary updated=0 unchanged=2 none=1 missing=0 foreign=0 failed=0",
        )

    def test_every_page_of_the_directory_is_read(self):
        with mock.patch.object(m, "PAGE", 2):
            self.federate()
        self.assertEqual(self.kc.puts, [self.directory])
        listed = m.federated_users(self.kc, LDAP_ID)
        self.assertEqual(
            [u["username"] for u in listed], ["biber", "administrator", "castor"]
        )

    def test_an_absent_provider_is_reported_and_changes_nothing(self):
        self.kc.components = []
        code, lines = self.federate()
        self.assertEqual(code, 0)
        self.assertEqual(self.kc.puts, [])
        self.assertEqual(lines[0], f"missing {LDAP_NAME}")


ROUTINES = (
    PROJECT_ROOT / "roles/web-app-keycloak/tasks/03_manager_ops/update_routines.yml"
)
TRUST = "tasks/update/06_users/email/federated.yml"
SETTINGS = "tasks/update/01_settings.yml"


def trust_precedes_settings(tasks: list[dict]) -> bool:
    """Whether the directory trust runs before the settings converge turns verifyEmail on.

    Args:
        tasks: the update routines, in include order.
    """
    includes = [str(task.get("include_tasks", "")) for task in tasks]
    position = {
        name: next(i for i, include in enumerate(includes) if include.endswith(name))
        for name in (TRUST, SETTINGS)
    }
    return position[TRUST] < position[SETTINGS]


class TestDirectoryTrustOrder(unittest.TestCase):
    def setUp(self):
        self.tasks = load_yaml_any(str(ROUTINES))

    def test_the_trust_runs_before_verify_email_turns_on(self):
        self.assertTrue(trust_precedes_settings(self.tasks))

    def test_a_trust_after_the_settings_converge_fails_the_check(self):
        trust = next(
            t for t in self.tasks if str(t.get("include_tasks", "")).endswith(TRUST)
        )
        swapped = [t for t in self.tasks if t is not trust] + [trust]
        self.assertFalse(trust_precedes_settings(swapped))

    def test_the_trust_runs_only_with_ldap_and_verify_email(self):
        trust = next(
            t for t in self.tasks if str(t.get("include_tasks", "")).endswith(TRUST)
        )
        self.assertEqual(
            trust["when"],
            [
                "KEYCLOAK_LDAP_ENABLED | bool",
                "KEYCLOAK_DICTIONARY_REALM.verifyEmail | bool",
            ],
        )


class TestMain(unittest.TestCase):
    def _run(self, kc, emails):
        out = io.StringIO()
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "EMAILS": json.dumps(emails),
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = m.main()
        return code, out.getvalue().splitlines()

    def test_the_summary_counts_every_outcome(self):
        kc = FakeKeycloak()
        kc.add_user("administrator", True, email="administrator@example.org")
        kc.add_user("biber", False, email="biber@example.org")
        kc.add_user("mapache", False, email="claimed@example.net")
        kc.add_user("castor", False)
        code, lines = self._run(
            kc,
            {
                "administrator": "administrator@example.org",
                "biber": "biber@example.org",
                "mapache": "mapache@example.org",
                "ghost": "ghost@example.org",
                "castor": "",
            },
        )
        self.assertEqual(code, 0)
        self.assertIn("foreign mapache", lines)
        self.assertIn("none castor", lines)
        self.assertEqual(
            lines[-1],
            "summary updated=1 unchanged=1 none=1 missing=1 foreign=1 failed=0",
        )

    def test_one_failed_user_fails_the_run_but_not_the_others(self):
        kc = FakeKeycloak()
        kc.add_user("administrator", False, email="administrator@example.org")
        kc.add_user("biber", False, email="biber@example.org")
        kc.failing.add("administrator")
        code, lines = self._run(
            kc,
            {
                "administrator": "administrator@example.org",
                "biber": "biber@example.org",
            },
        )
        self.assertEqual(code, 1)
        self.assertIn("failed administrator", lines)
        self.assertIn("updated biber", lines)

    def test_a_missing_environment_key_fails_before_any_call(self):
        kc = FakeKeycloak()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = m.main()
        self.assertEqual(code, 1)
        self.assertTrue(out.getvalue().startswith("setup-failed"))

    def test_emails_that_are_no_username_to_address_object_fail_before_any_call(
        self,
    ):
        kc = FakeKeycloak()
        kc.add_user("biber", False, email="biber@example.org")
        out = io.StringIO()
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "EMAILS": json.dumps(["biber"]),
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            contextlib.redirect_stdout(out),
        ):
            code = m.main()
        self.assertEqual(code, 1)
        self.assertTrue(out.getvalue().startswith("setup-failed"))
        self.assertEqual(kc.puts, [])


if __name__ == "__main__":
    unittest.main()
