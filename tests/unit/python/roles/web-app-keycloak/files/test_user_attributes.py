import contextlib
import copy
import io
import json
import os
import re
import sys
import unittest
import unittest.mock as mock
import urllib.parse

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import user_attributes as m

ATTRIBUTE = "nextcloud_uid"
TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks/utils/user_attributes.yml"
JINJA = Environment(autoescape=True)
JINJA.filters["from_json"] = json.loads
JINJA.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
    pattern, repl, value
)
JINJA.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None


class FakeKeycloak:
    def __init__(self, drops=False):
        self.users = {}
        self.calls = []
        self.puts = []
        self.failing = set()
        self.drops = drops

    def add_user(self, user_id, username=None, **attributes):
        self.users[user_id] = {
            "id": user_id,
            "username": username or f"user-{user_id}",
            "email": f"{user_id}@example.com",
            "attributes": {name: list(values) for name, values in attributes.items()},
        }

    def search(self, query):
        params = dict(urllib.parse.parse_qsl(query))
        term = params["username"].lower()
        exact = params.get("exact") == "true"
        return [
            {"id": user["id"], "username": user["username"]}
            for user in self.users.values()
            if (user["username"] == term if exact else term in user["username"])
        ]

    def call(self, method, path, payload=None, timeout=60):
        self.calls.append((method, path))
        resource, _, query = path.partition("?")
        if resource == "users" and method == "GET":
            return self.search(query), ""
        user_id = resource.removeprefix("users/")
        if user_id in self.failing:
            raise m.KeycloakError(f"{method} {path}: HTTP 500")
        if user_id not in self.users:
            raise m.KeycloakError(f"{method} {path}: HTTP 404")
        if method == "GET":
            return copy.deepcopy(self.users[user_id]), ""
        self.puts.append((user_id, copy.deepcopy(payload)))
        if not self.drops:
            self.users[user_id] = copy.deepcopy(payload)
        return None, ""


def run(kc, users):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = m.run(kc, ATTRIBUTE, users)
    lines = out.getvalue().splitlines()
    (state,) = [line for line in lines if line.startswith("USER_ATTRIBUTES ")]
    results = json.loads(state.removeprefix("USER_ATTRIBUTES "))
    return code, {result["id"]: result for result in results}, lines


class TestUserAttributes(unittest.TestCase):
    def test_an_empty_attribute_gets_the_value_and_keeps_the_rest_of_the_user(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", mailbox=["a@example.com"])
        code, results, _ = run(kc, [{"id": "sub-1", "value": "keycloak-sub-1"}])
        self.assertEqual(code, 0)
        self.assertEqual(results["sub-1"]["outcome"], "updated")
        self.assertEqual(results["sub-1"]["held"], [])
        ((user_id, written),) = kc.puts
        self.assertEqual(user_id, "sub-1")
        self.assertEqual(
            written["attributes"],
            {"mailbox": ["a@example.com"], ATTRIBUTE: ["keycloak-sub-1"]},
        )
        self.assertEqual(written["email"], "sub-1@example.com")

    def test_the_same_value_is_left_alone(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", **{ATTRIBUTE: ["keycloak-sub-1"]})
        code, results, _ = run(kc, [{"id": "sub-1", "value": "keycloak-sub-1"}])
        self.assertEqual(code, 0)
        self.assertEqual(results["sub-1"]["outcome"], "unchanged")
        self.assertEqual(kc.puts, [])

    def test_a_different_value_is_a_conflict_that_keeps_it(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", **{ATTRIBUTE: ["alice"]})
        code, results, _ = run(kc, [{"id": "sub-1", "value": "keycloak-sub-1"}])
        self.assertEqual(code, 0)
        self.assertEqual(results["sub-1"]["outcome"], "conflict")
        self.assertEqual(results["sub-1"]["held"], ["alice"])
        self.assertEqual(kc.puts, [])
        self.assertEqual(kc.users["sub-1"]["attributes"][ATTRIBUTE], ["alice"])

    def test_a_second_entry_for_the_same_user_conflicts_with_the_first(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1")
        _, _, lines = run(
            kc,
            [
                {"id": "sub-1", "value": "keycloak-sub-1"},
                {"id": "sub-1", "value": "carol"},
            ],
        )
        self.assertEqual(lines[:2], ["updated sub-1", "conflict sub-1"])

    def test_another_user_s_username_as_value_is_taken_and_left_unwritten(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1")
        kc.add_user("sub-2", username="alice")
        code, results, _ = run(kc, [{"id": "sub-1", "value": "Alice"}])
        self.assertEqual(code, 0)
        self.assertEqual(results["sub-1"]["outcome"], "taken")
        self.assertEqual(kc.puts, [])

    def test_a_held_value_another_user_has_as_username_is_taken(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", **{ATTRIBUTE: ["alice"]})
        kc.add_user("sub-2", username="alice")
        _, results, _ = run(kc, [{"id": "sub-1", "value": "alice"}])
        self.assertEqual(results["sub-1"]["outcome"], "taken")

    def test_the_own_username_or_a_longer_one_of_another_user_is_not_taken(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", username="alice")
        kc.add_user("sub-2", username="alice-smith")
        _, results, _ = run(kc, [{"id": "sub-1", "value": "alice"}])
        self.assertEqual(results["sub-1"]["outcome"], "updated")

    def test_users_handed_the_same_value_do_not_take_it_from_each_other(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1", username="bob")
        kc.add_user("sub-2", username="alice")
        _, results, _ = run(
            kc,
            [{"id": "sub-1", "value": "alice"}, {"id": "sub-2", "value": "alice"}],
        )
        self.assertEqual(
            {user_id: result["outcome"] for user_id, result in results.items()},
            {"sub-1": "updated", "sub-2": "updated"},
        )

    def test_a_user_absent_from_the_realm_is_missing(self):
        code, results, _ = run(FakeKeycloak(), [{"id": "sub-9", "value": "x"}])
        self.assertEqual(code, 0)
        self.assertEqual(results["sub-9"]["outcome"], "missing")

    def test_an_id_a_url_would_resolve_above_the_user_is_missing_without_a_call(self):
        # nocheck: project-root-import  Keycloak user ids, not paths
        for user_id in ("", ".", ".."):
            with self.subTest(user_id=user_id):
                kc = FakeKeycloak()
                _, results, _ = run(kc, [{"id": user_id, "value": "x"}])
                self.assertEqual(results[user_id]["outcome"], "missing")
                self.assertEqual(kc.calls, [])

    def test_a_write_keycloak_drops_is_reported_as_dropped(self):
        kc = FakeKeycloak(drops=True)
        kc.add_user("sub-1")
        _, results, _ = run(kc, [{"id": "sub-1", "value": "keycloak-sub-1"}])
        self.assertEqual(results["sub-1"]["outcome"], "dropped")

    def test_a_failing_user_fails_the_run_after_the_others(self):
        kc = FakeKeycloak()
        kc.add_user("sub-1")
        kc.add_user("sub-2")
        kc.failing.add("sub-1")
        code, results, lines = run(
            kc,
            [{"id": "sub-1", "value": "a"}, {"id": "sub-2", "value": "b"}],
        )
        self.assertEqual(code, 1)
        self.assertEqual(results["sub-1"]["outcome"], "failed")
        self.assertEqual(results["sub-2"]["outcome"], "updated")
        self.assertIn(
            "summary updated=1 unchanged=0 conflict=0 taken=0 missing=0 dropped=0 failed=1",
            lines,
        )

    def test_unreadable_input_stops_before_any_call(self):
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "ATTRIBUTE": ATTRIBUTE,
        }
        for users in ("not json", '[{"value": "x"}]', "[1]"):
            with (
                self.subTest(users=users),
                mock.patch.dict(os.environ, {**env, "USERS": users}, clear=True),
                mock.patch.object(m, "container_credentials", return_value=("u", "p")),
                mock.patch.object(m, "run") as runner,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(m.main(), 2)
                runner.assert_not_called()


class TestUserAttributesTasks(unittest.TestCase):
    def test_one_rest_run_writes_every_value_and_its_outcomes_become_the_output(
        self,
    ):
        (stack_host,) = load_yaml_any(str(TASKS), default_if_missing=[])
        self.assertEqual(stack_host["when"], "IS_STACK_HOST | bool")
        write, store = stack_host["block"]
        self.assertEqual(write["when"], "keycloak_user_attribute_values | length > 0")
        run_task = write["block"][1]
        params = run_task["vars"]
        self.assertEqual(
            run_task["ansible.builtin.include_tasks"]["apply"],
            {"delegate_to": "{{ KEYCLOAK_HOST_NODE }}"},
        )
        self.assertEqual(params["rest_script"], "user_attributes.py")
        self.assertEqual(
            params["rest_script_env"]["USERS"],
            "{{ keycloak_user_attribute_values | to_json }}",
        )
        self.assertEqual(params["rest_script_ok_rcs"], [0, 1])
        kc = FakeKeycloak()
        kc.add_user("sub-1")
        values = [{"id": "sub-1", "value": "a"}, {"id": "sub-9", "value": "b"}]
        _, results, lines = run(kc, values)
        template = store["ansible.builtin.set_fact"]["keycloak_user_attribute_results"]
        output = JINJA.compile_expression(
            template.strip().removeprefix("{{").removesuffix("}}")
        )
        self.assertEqual(
            output(
                keycloak_user_attribute_values=values,
                keycloak_user_attribute_run={"stdout_lines": lines},
            ),
            [results["sub-1"], results["sub-9"]],
        )
        self.assertEqual(output(keycloak_user_attribute_values=[]), [])
        summary = next(line for line in lines if line.startswith("summary "))
        self.assertRegex(summary, params["rest_script_changed"])
        self.assertNotRegex(
            summary.replace("updated=1", "updated=0"), params["rest_script_changed"]
        )


if __name__ == "__main__":
    unittest.main()
