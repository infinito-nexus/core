from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

APP = "web-app-gitea"
ROLE_DIR = PROJECT_ROOT / "roles" / APP
SETUP_TASKS = ROLE_DIR / "tasks" / "setup" / "ldap.yml"
CLEANUP_TASKS = ROLE_DIR / "tasks" / "cleanup" / "ldap.yml"
USERS_SQL = ROLE_DIR / "files" / "sql" / "auth-source-users.sql"
PLUGIN = ROLE_DIR / "filter_plugins" / "gitea_ldap_source_plan.py"
AWK_LOOKUP = re.compile(
    r"awk -F '(?P<sep>[^']+)' -v (?P<var>\w+)=\{\{ GITEA_LDAP_SOURCE_TYPE \| quote \}\} "
    r"'(?P<program>[^']+)'"
)
PROVIDER_COLUMN_WIDTH = 25
NAME_COLUMN_WIDTH = 255
HEADER = "ID\tName\t\t\t\tType\t\t\tEnabled\n"
OAUTH2_ROW = "4\tSSO Login (INFINITO.NEXUS)\tOAuth2\t\t\ttrue\n"
PRODUCTION_LISTING = (
    HEADER
    + "3\tLDAP (infinito.nexus)\t\tLDAP (via BindDN)\ttrue\n"
    + "1\tLDAP (Infinito.Nexus)\t\tLDAP (via BindDN)\ttrue\n"
    + OAUTH2_ROW
)
LOOKALIKE_LISTING = (
    HEADER
    + "2\tLDAP (example.org)\t\tLDAP (simple auth)\ttrue\n"
    + "5\tLDAP (via BindDN)\t\tOAuth2\t\t\ttrue\n"
)

_spec = importlib.util.spec_from_file_location("gitea_ldap_source_plan", PLUGIN)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
gitea_ldap_source_plan = _mod.gitea_ldap_source_plan


def role_vars() -> dict:
    return load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))


def awk_lookup(task_path) -> re.Match[str]:
    match = AWK_LOOKUP.search(read_text(str(task_path)))
    if match is None:
        raise AssertionError(
            f"{task_path} looks the LDAP source up without awk by type"
        )
    return match


def run_awk(listing: str, *args: str) -> list[str]:
    return subprocess.run(
        [shutil.which("awk"), *args],
        input=listing,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


def lookup(task_path, listing: str) -> list[str]:
    """Run the awk lookup of ``task_path`` on ``listing``.

    Args:
        task_path: the task file that carries the lookup.
        listing: what ``gitea admin auth list`` prints.

    Returns:
        The IDs the lookup prints.
    """
    match = awk_lookup(task_path)
    source_type = role_vars()["GITEA_LDAP_SOURCE_TYPE"]
    return run_awk(
        listing,
        "-F",
        match["sep"],
        "-v",
        f"{match['var']}={source_type}",
        match["program"],
    )


def converge(listing: str, linked: dict[str, int]) -> dict[str, str]:
    """Apply the setup's lookup, plan, delete and add or update to ``listing``.

    Args:
        listing: what ``gitea admin auth list`` prints.
        linked: users linked to each source ID of ``listing``.

    Returns:
        The LDAP sources after the setup ran, by ID.
    """
    source_type = role_vars()["GITEA_LDAP_SOURCE_TYPE"]
    name = role_vars()["GITEA_LDAP_SOURCE_NAME"]
    rows = [re.split(r"\t+", line) for line in listing.splitlines()[1:]]
    ids = lookup(SETUP_TASKS, listing)
    user_rows = [[row[0], str(linked[row[0]])] for row in rows] if len(ids) > 1 else []
    plan = gitea_ldap_source_plan(ids, user_rows)
    sources = {row[0]: row[1] for row in rows if row[2] == source_type}
    for source_id in plan["delete"]:
        if linked[source_id]:
            raise AssertionError(f"Gitea refuses to delete source {source_id} in use")
        del sources[source_id]
    if plan["keep"]:
        sources[plan["keep"]] = name
    else:
        sources[str(max([0, *(int(row[0]) for row in rows)]) + 1)] = name
    return sources


class TestLdapSourceLookup(unittest.TestCase):
    def test_one_source_is_found(self) -> None:
        listing = HEADER + "1\tLDAP\t\tLDAP (via BindDN)\ttrue\n" + OAUTH2_ROW
        self.assertEqual(lookup(SETUP_TASKS, listing), ["1"])

    def test_both_duplicates_are_found(self) -> None:
        self.assertEqual(lookup(SETUP_TASKS, PRODUCTION_LISTING), ["3", "1"])

    def test_no_source_yields_no_id(self) -> None:
        self.assertEqual(lookup(SETUP_TASKS, HEADER + OAUTH2_ROW), [])
        self.assertEqual(lookup(SETUP_TASKS, HEADER), [])

    def test_simple_auth_and_a_lookalike_name_are_not_the_role_source(self) -> None:
        self.assertEqual(lookup(SETUP_TASKS, LOOKALIKE_LISTING), [])

    def test_cleanup_finds_the_sources_by_type(self) -> None:
        self.assertEqual(lookup(CLEANUP_TASKS, PRODUCTION_LISTING), ["3", "1"])
        self.assertEqual(lookup(CLEANUP_TASKS, LOOKALIKE_LISTING), [])
        self.assertEqual(
            awk_lookup(CLEANUP_TASKS).groupdict(), awk_lookup(SETUP_TASKS).groupdict()
        )

    def test_the_former_name_lookups_miss_the_duplicate(self) -> None:
        self.assertEqual(
            [
                line.partition("\t")[0]
                for line in PRODUCTION_LISTING.splitlines()[1:]
                if "LDAP (infinito.nexus)" in line
            ],
            ["3"],
        )
        self.assertEqual(
            run_awk(
                PRODUCTION_LISTING,
                "-v",
                "name=LDAP (Infinito.Nexus)",
                "$0 ~ name {print $1; exit}",
            ),
            [],
        )


class TestLdapSourcePlan(unittest.TestCase):
    def test_no_source_is_added(self) -> None:
        self.assertEqual(gitea_ldap_source_plan([], []), {"keep": "", "delete": []})

    def test_a_single_source_is_updated_without_counting(self) -> None:
        self.assertEqual(gitea_ldap_source_plan(["3"], []), {"keep": "3", "delete": []})

    def test_the_source_users_are_linked_to_is_kept(self) -> None:
        rows = [["1", "0"], ["3", "7"], ["4", "2"]]
        self.assertEqual(
            gitea_ldap_source_plan(["3", "1"], rows), {"keep": "3", "delete": ["1"]}
        )
        rows = [["1", "7"], ["3", "0"], ["4", "2"]]
        self.assertEqual(
            gitea_ldap_source_plan(["3", "1"], rows), {"keep": "1", "delete": ["3"]}
        )

    def test_without_users_the_lowest_id_is_kept(self) -> None:
        rows = [["1", "0"], ["3", "0"], ["4", "2"]]
        self.assertEqual(
            gitea_ldap_source_plan(["3", "1", "10"], [*rows, ["10", "0"]]),
            {"keep": "1", "delete": ["3", "10"]},
        )

    def test_users_on_two_sources_fail_loud(self) -> None:
        rows = [["1", "4"], ["3", "1"]]
        with self.assertRaisesRegex(
            AnsibleFilterError, "id 1: 4 linked, id 3: 1 linked"
        ):
            gitea_ldap_source_plan(["3", "1"], rows)
        with self.assertRaisesRegex(AnsibleFilterError, "move every user"):
            gitea_ldap_source_plan(["3", "1"], rows)

    def test_a_source_the_database_does_not_know_fails_loud(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "no login_source row"):
            gitea_ldap_source_plan(["3", "1"], [["1", "0"]])
        with self.assertRaisesRegex(AnsibleFilterError, "no login_source row"):
            gitea_ldap_source_plan(["3", "1"], [])


class TestLdapSourceConvergence(unittest.TestCase):
    def test_duplicates_with_users_on_one_converge_to_that_source(self) -> None:
        self.assertEqual(
            converge(PRODUCTION_LISTING, {"1": 12, "3": 0, "4": 3}),
            {"1": role_vars()["GITEA_LDAP_SOURCE_NAME"]},
        )

    def test_duplicates_without_users_converge_to_the_lowest_id(self) -> None:
        self.assertEqual(
            converge(PRODUCTION_LISTING, {"1": 0, "3": 0, "4": 0}),
            {"1": role_vars()["GITEA_LDAP_SOURCE_NAME"]},
        )

    def test_duplicates_with_users_on_both_are_left_alone(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            converge(PRODUCTION_LISTING, {"1": 12, "3": 2, "4": 3})

    def test_a_fresh_instance_gets_one_source(self) -> None:
        self.assertEqual(
            converge(HEADER + OAUTH2_ROW, {"4": 0}),
            {"5": role_vars()["GITEA_LDAP_SOURCE_NAME"]},
        )

    def test_a_converged_instance_stays_at_one_source(self) -> None:
        name = role_vars()["GITEA_LDAP_SOURCE_NAME"]
        listing = HEADER + f"1\t{name}\t\tLDAP (via BindDN)\ttrue\n" + OAUTH2_ROW
        self.assertEqual(converge(listing, {"1": 12, "4": 3}), {"1": name})


class TestLdapSourceDefinition(unittest.TestCase):
    def test_one_fixed_short_name_is_defined_once(self) -> None:
        values = role_vars()
        name = values["GITEA_LDAP_SOURCE_NAME"]
        self.assertNotIn("{{", name)
        self.assertLessEqual(len(name), PROVIDER_COLUMN_WIDTH)
        self.assertLessEqual(len(name), NAME_COLUMN_WIDTH)
        self.assertEqual(
            values["GITEA_LDAP_AUTH_ARGS"][0], '--name "{{ GITEA_LDAP_SOURCE_NAME }}"'
        )

    def test_the_count_matches_the_in_use_check_of_gitea(self) -> None:
        sql = read_text(str(USERS_SQL))
        self.assertIn("u.login_source = s.id", sql)
        self.assertIn("e.login_source_id = s.id", sql)
        self.assertTrue(sql.lstrip().upper().startswith("SELECT "))


class TestLdapBindPasswordOffArgv(unittest.TestCase):
    def _manage_tasks(self) -> list[dict]:
        tasks = load_yaml_str(read_text(str(SETUP_TASKS)))
        return [
            task
            for task in tasks
            if "add-ldap" in task.get("shell", "")
            or "update-ldap" in task.get("shell", "")
        ]

    def test_the_shared_args_carry_no_password(self) -> None:
        self.assertFalse(
            any("bind-password" in arg for arg in role_vars()["GITEA_LDAP_AUTH_ARGS"])
        )

    def test_add_and_update_read_the_password_from_stdin(self) -> None:
        tasks = self._manage_tasks()
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertEqual(task["args"]["stdin"], "{{ LDAP.BIND_CREDENTIAL }}")
            self.assertEqual(task["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
            self.assertNotIn("BIND_CREDENTIAL", task["shell"])
            self.assertNotIn("environment", task)
            self.assertIn("IFS= read -r GITEA_LDAP_BIND_PASSWORD", task["shell"])
            self.assertIn("-e GITEA_LDAP_BIND_PASSWORD", task["shell"])
            self.assertIn('--bind-password "$GITEA_LDAP_BIND_PASSWORD"', task["shell"])

    def test_the_password_is_only_expanded_by_the_inner_shell(self) -> None:
        for task in self._manage_tasks():
            host, inner = task["shell"].split("sh -lc '", 1)
            self.assertNotIn("$GITEA_LDAP_BIND_PASSWORD", host)
            self.assertNotIn("${GITEA_LDAP_BIND_PASSWORD", host)
            self.assertIn('"$GITEA_LDAP_BIND_PASSWORD"', inner)
            self.assertIn('"${GITEA_LDAP_BIND_PASSWORD:?', inner)

    def test_the_shared_args_keep_the_inner_quoting_intact(self) -> None:
        self.assertFalse(any("'" in arg for arg in role_vars()["GITEA_LDAP_AUTH_ARGS"]))


if __name__ == "__main__":
    unittest.main()
