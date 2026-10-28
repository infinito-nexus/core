from __future__ import annotations

import base64
import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles" / "web-app-openproject"
GATE = ROLE / "tasks" / "04_admin.yml"
STATE = ROLE / "tasks" / "04_admin" / "state.yml"
PROVISION = ROLE / "tasks" / "04_admin" / "provision.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN
SERVICES = ROLE / ROLE_FILE_META_SERVICES
QUERY = ROLE / "files" / "sql" / "select-admin-state.sql"

FIRST_READ = "📖 Read the settings, administrator and LDAP link OpenProject holds"
READ = "🔍 Read the settings, administrator and LDAP link OpenProject holds"
DIGEST = "🧮 Digest the run's sources, inputs and the state OpenProject holds"
DECIDE = "🧮 Decide whether the settings and administrator need a run"
GATED = "🔧 Run the settings and administrator step and stamp what it left"
RUN = "🔧 Apply settings, ensure the administrator and link it to LDAP"
REREAD = "📖 Read the settings, administrator and LDAP link the run left"
STAMP = "📝 Stamp the settings, administrator and LDAP link the run left"

SETTINGS = {
    "email_delivery_method": "smtp",
    "smtp_address": "mail.infinito.example",
    "smtp_domain": "infinito.example",
    "smtp_user_name": "no-reply@infinito.example",
    "smtp_password": "smtp-token",
    "smtp_ssl": False,
}
STORED_SETTINGS = "email_delivery_method=a1,smtp_address=b2,smtp_password=c3"
STEADY = {
    "id": "7",
    "admin": "t",
    "status": "1",
    "force_password_change": "f",
    "ldap_auth_source_id": "3",
    "password_id": "41",
    "password_md5": "9f86d081",
    "ldap_source_id": "3",
    "settings": STORED_SETTINGS,
}
ABSENT = {
    "changed": False,
    "skipped": True,
    "false_condition": "openproject_admin_stamp_file.stat.exists",
}


def _row(**changes: str) -> list[str]:
    """Return the row the state query yields, in its column order.

    Args:
      changes: columns whose value differs from the steady state.
    """
    return list({**STEADY, **changes}.values())


def _flat(tasks: list[dict]) -> list[dict]:
    """Return the tasks in run order, each block followed by its children.

    Args:
      tasks: parsed task list of one task file.
    """
    flat: list[dict] = []
    for task in tasks:
        flat.append(task)
        flat.extend(_flat(task.get("block") or []))
    return flat


def _tasks(path) -> list[dict]:
    return _flat(load_yaml_any(str(path), default_if_missing=[]))


def _task(path, name: str) -> dict:
    return next(task for task in _tasks(path) if task.get("name") == name)


def _render(template, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _sources() -> list[str]:
    raw = load_yaml_any(str(VARS))["OPENPROJECT_ADMIN_SOURCES"]
    return [_render(item, role_path=str(ROLE)) for item in raw]


INPUTS = {
    "OPENPROJECT_ADMIN_SOURCES": _sources(),
    "OPENPROJECT_VERSION": "17",
    "OPENPROJECT_ADMINISTRATOR_USERNAME": "administrator",
    "OPENPROJECT_ADMINISTRATOR_EMAIL": "administrator@infinito.example",
    "OPENPROJECT_ADMINISTRATOR_PASSWORD": "Sw0rdf1sh!",
    "OPENPROJECT_RAILS_SETTINGS": SETTINGS,
    "OPENPROJECT_ADMIN_LDAP_NAME": "infinito.example",
}


def _digest(row: list[str], **inputs) -> str:
    """Render the digest the state step records.

    Args:
      row: the one row the state query returns.
      inputs: overrides of the role variables in INPUTS.
    """
    expression = _task(STATE, DIGEST)["ansible.builtin.set_fact"][
        "openproject_admin_digest"
    ]
    return _render(
        expression,
        **{**INPUTS, **inputs},
        openproject_admin_state={"rows": [row]},
    )


def _stamp(digest: str) -> dict:
    """Return the slurp result of a stamp holding ``digest``.

    Args:
      digest: the digest the stamp file holds.
    """
    content = base64.b64encode(f"{digest}\n".encode()).decode()
    return {"changed": False, "content": content, "encoding": "base64"}


def _decision() -> str:
    return _task(GATE, DECIDE)["ansible.builtin.set_fact"]["openproject_admin_due"]


def _due(stamp: dict, digest: str, force=False, decision: str = "") -> bool:
    """Render whether the settings and administrator run is due.

    Args:
      stamp: the registered slurp result of the stamp file.
      digest: the digest of the current sources, inputs and state.
      force: the value of services.openproject.admin.force.
      decision: the decision expression; the gate's own when empty.
    """
    due = _render(
        decision or _decision(),
        OPENPROJECT_ADMIN_FORCE=force,
        openproject_admin_stamp=stamp,
        openproject_admin_digest=digest,
    )
    return _render("{{ due | bool }}", due=due)


class TestDecision(unittest.TestCase):
    def setUp(self):
        self.digest = _digest(_row())

    def test_a_missing_stamp_runs_the_step(self):
        self.assertTrue(_due(ABSENT, self.digest))

    def test_a_stamp_equal_to_the_digest_skips_the_step(self):
        self.assertFalse(_due(_stamp(self.digest), self.digest))

    def test_a_stamp_different_from_the_digest_runs_the_step(self):
        rotated = _digest(_row(), OPENPROJECT_ADMINISTRATOR_PASSWORD="rotated")
        self.assertTrue(_due(_stamp(rotated), self.digest))

    def test_force_runs_the_step_on_an_equal_stamp(self):
        for force in (True, "true"):
            with self.subTest(force=force):
                self.assertTrue(_due(_stamp(self.digest), self.digest, force=force))

    def test_negative_control_a_gate_blind_to_the_digest_misses_the_drift(self):
        blind = _decision().replace(
            "!= openproject_admin_digest",
            "!= (openproject_admin_stamp.content | b64decode | trim)",
        )
        self.assertNotEqual(blind, _decision())
        demoted = _stamp(_digest(_row(admin="f")))
        self.assertFalse(_due(demoted, self.digest, decision=blind))
        self.assertTrue(_due(demoted, self.digest))


class TestDigest(unittest.TestCase):
    def test_the_same_sources_inputs_and_state_give_the_same_digest(self):
        self.assertEqual(_digest(_row()), _digest(_row()))
        self.assertRegex(_digest(_row()), r"^[0-9a-f]{64}$")

    def test_drift_in_openproject_changes_the_digest(self):
        removed = dict.fromkeys(list(STEADY)[:7], "")
        drifts = {
            "administrator removed": _row(**removed),
            "administrator demoted": _row(admin="f"),
            "administrator locked": _row(status="3"),
            "password change forced": _row(force_password_change="t"),
            "LDAP link dropped": _row(ldap_auth_source_id=""),
            "password changed in the UI": _row(password_id="42", password_md5="e3b0"),
            "password rehashed in place": _row(password_md5="e3b0"),
            "LDAP source replaced": _row(ldap_source_id="4"),
            "setting edited in the UI": _row(
                settings=STORED_SETTINGS.replace("c3", "d4")
            ),
            "setting deleted": _row(settings="email_delivery_method=a1"),
        }
        steady = _digest(_row())
        for drift, row in drifts.items():
            with self.subTest(drift=drift):
                self.assertEqual(len(row), len(STEADY))
                self.assertNotEqual(_digest(row), steady)

    def test_changed_inputs_change_the_digest(self):
        changes = {
            "OPENPROJECT_ADMINISTRATOR_PASSWORD": "rotated",
            "OPENPROJECT_ADMINISTRATOR_USERNAME": "root",
            "OPENPROJECT_ADMINISTRATOR_EMAIL": "root@infinito.example",
            "OPENPROJECT_RAILS_SETTINGS": {**SETTINGS, "smtp_password": "rotated"},
            "OPENPROJECT_ADMIN_LDAP_NAME": "",
            "OPENPROJECT_VERSION": "18",
            "OPENPROJECT_ADMIN_SOURCES": [
                str(ROLE / "files" / "ruby" / "drain_jobs.rb"),
                *INPUTS["OPENPROJECT_ADMIN_SOURCES"][1:],
            ],
        }
        steady = _digest(_row())
        for name, value in changes.items():
            with self.subTest(input=name):
                self.assertNotEqual(_digest(_row(), **{name: value}), steady)

    def test_secrets_reach_the_digest_only_hashed(self):
        expression = _task(STATE, DIGEST)["ansible.builtin.set_fact"][
            "openproject_admin_digest"
        ]
        for entry in (
            "'password': OPENPROJECT_ADMINISTRATOR_PASSWORD | hash('sha256')",
            (
                "'settings': OPENPROJECT_RAILS_SETTINGS | to_json(sort_keys=true)"
                " | hash('sha256')"
            ),
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, expression)


class TestSources(unittest.TestCase):
    def test_every_file_the_run_reads_is_a_source(self):
        provision = read_text(str(PROVISION))
        read = {
            str(ROLE / "files" / name)
            for name in re.findall(r"lookup\('file', '([^']+)'\)", provision)
        }
        self.assertEqual(len(read), 3)
        self.assertLessEqual(read | {str(PROVISION)}, set(_sources()))

    def test_every_source_exists(self):
        for source in _sources():
            with self.subTest(source=source):
                self.assertTrue(read_text(source))


class TestQuery(unittest.TestCase):
    def test_the_query_reads_what_the_scripts_write(self):
        sql = read_text(str(QUERY))
        for fragment in (
            "account.admin",
            "account.status",
            "account.force_password_change",
            "account.ldap_auth_source_id",
            "FROM user_passwords",
            "JOIN ldap_auth_sources",
            "FROM settings",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, sql)

    def test_the_query_returns_hashes_not_secrets(self):
        sql = read_text(str(QUERY))
        secrets = [
            match
            for match in re.finditer(r"(\w+)\.(hashed_password|value)\b", sql)
            if match.group(1) != "candidate"
        ]
        self.assertEqual(len(secrets), 2)
        for match in secrets:
            with self.subTest(column=match.group(0)):
                self.assertEqual(sql[match.start() - 4 : match.start()], "md5(")

    def test_the_query_reads_exactly_the_settings_the_run_applies(self):
        args = _task(STATE, READ)["database_query"]["named_args"]
        names = _render(args["settings"], OPENPROJECT_RAILS_SETTINGS=SETTINGS)
        self.assertEqual(json.loads(names), list(SETTINGS))
        self.assertEqual(args["ldap_name"], "{{ OPENPROJECT_ADMIN_LDAP_NAME }}")
        self.assertEqual(args["login"], "{{ OPENPROJECT_ADMINISTRATOR_USERNAME }}")


class TestWiring(unittest.TestCase):
    def test_the_run_is_followed_by_a_reread_and_a_stamp(self):
        names = [task["name"] for task in _tasks(GATE)]
        order = [names.index(n) for n in (FIRST_READ, DECIDE, RUN, REREAD, STAMP)]
        self.assertEqual(order, sorted(order))

    def test_run_reread_and_stamp_wait_for_the_decision(self):
        gated = _task(GATE, GATED)
        self.assertEqual(gated["when"], "openproject_admin_due | bool")
        self.assertEqual(
            [task["name"] for task in gated["block"]], [RUN, REREAD, STAMP]
        )

    def test_both_state_reads_are_masked(self):
        for name in (FIRST_READ, REREAD):
            with self.subTest(task=name):
                include = _task(GATE, name)["include_tasks"]
                self.assertEqual(include["file"], "04_admin/state.yml")
                self.assertEqual(
                    include["apply"]["no_log"],
                    "{{ MASK_CREDENTIALS_IN_LOGS | bool }}",
                )

    def test_the_stamp_holds_only_the_digest_and_only_for_its_owner(self):
        stamp = _task(GATE, STAMP)["stack_host_copy"]
        self.assertEqual(stamp["content"], "{{ openproject_admin_digest }}\n")
        self.assertEqual(stamp["mode"], "0600")
        self.assertEqual(stamp["dest"], "{{ OPENPROJECT_ADMIN_STAMP_FILE }}")
        self.assertIn(
            "directories.instance",
            load_yaml_any(str(VARS))["OPENPROJECT_ADMIN_STAMP_FILE"],
        )

    def test_the_force_flag_is_declared_off(self):
        openproject = load_yaml_any(str(SERVICES))["openproject"]
        self.assertIs(openproject["admin"]["force"], False)
        self.assertIn(
            "'services.openproject.admin.force'",
            load_yaml_any(str(VARS))["OPENPROJECT_ADMIN_FORCE"],
        )

    def test_the_link_uses_the_ldap_name_the_state_reads(self):
        provision = read_text(str(PROVISION))
        self.assertIn("OPENPROJECT_ADMIN_LDAP_NAME", provision)
        self.assertNotIn("OPENPROJECT_LDAP.name", provision)


if __name__ == "__main__":
    unittest.main()
