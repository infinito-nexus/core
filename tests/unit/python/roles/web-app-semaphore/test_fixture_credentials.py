from __future__ import annotations

import importlib.util
import unittest

import jinja2
from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import FilterModule as CoreFilters

from tests.utils.openbao_stub import OpenBaoStub
from utils import openbao_client
from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_USERS,
    ROLE_FILE_VARS_MAIN,
)

from ._gates import gated_tasks
from .test_fixture_commit import credential_reads, fixture_scope

ROLE = ROLES_DIR / "web-app-semaphore"
OPENBAO = ROLES_DIR / "web-app-openbao"
WRITER = ROLE / "tasks" / "utils" / "project" / "fixture" / "credentials.yml"
INPUTS = ROLE / "tasks" / "utils" / "project" / "inputs.yml"
IDENTITY = ROLE / "tasks" / "utils" / "workspaces" / "identity.yml"
ROOT = "fixture/platform"
RUNNING = ["web-app-openbao", "web-app-semaphore", "web-svc-seaweedfs"]
CONSUMERS = ["web-app-nextcloud"]
TOKEN = "s.fixture-reader"


def _load():
    path = ROLE / "filter_plugins" / "semaphore_fixture.py"
    spec = importlib.util.spec_from_file_location("semaphore_fixture", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _load()


def environment():
    jinja = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    jinja.filters.update(CoreFilters().filters())
    return jinja


def role_vars(role):
    return load_yaml_any(str(role / ROLE_FILE_VARS_MAIN))


def declared():
    return role_vars(ROLE)["SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_CREDENTIALS"]


def secrets(running=RUNNING, consumers=CONSUMERS):
    return fixture.semaphore_fixture_secrets(declared(), ROOT, running, consumers)


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


class TestFixtureSecrets(unittest.TestCase):
    def test_the_layout_follows_127_decision_3(self):
        found = {entry["path"]: entry["fields"] for entry in secrets()}
        self.assertEqual(
            found,
            {
                "fixture/platform/users/platform_administrator": ["password"],
                "fixture/platform/apps/web-app-openbao": [
                    "approle_role_id",
                    "approle_secret_id",
                ],
                "fixture/platform/apps/web-app-semaphore": sorted(
                    declared()["applications"]["web-app-semaphore"]
                ),
            },
        )

    def test_an_objstore_consumer_the_platform_runs_adds_its_key(self):
        found = secrets(running=[*RUNNING, *CONSUMERS])
        self.assertIn(
            {
                "kind": "apps",
                "name": "web-app-nextcloud",
                "path": "fixture/platform/apps/web-app-nextcloud",
                "fields": ["objstore_secret_key"],
            },
            found,
        )

    def test_negative_control_an_application_the_platform_does_not_run_is_left_out(
        self,
    ):
        paths = [entry["path"] for entry in secrets(running=["web-app-openbao"])]
        self.assertNotIn("fixture/platform/apps/svc-dns-knot", paths)
        self.assertNotIn("fixture/platform/apps/web-app-semaphore", paths)

    def test_every_declared_credential_is_one_its_role_declares(self):
        for application_id, names in declared()["applications"].items():
            schema = load_yaml_any(
                str(ROLES_DIR / application_id / ROLE_FILE_META_SECRETS)
            )
            with self.subTest(application_id=application_id):
                self.assertEqual(sorted(set(names) - set(schema["credentials"])), [])
        users = set()
        for path in ROLES_DIR.glob(f"*/{ROLE_FILE_META_USERS}"):
            users |= set(load_yaml_any(str(path)) or {})
        self.assertEqual(sorted(set(declared()["users"]) - users), [])

    def test_the_fields_refuse_a_credential_the_application_lacks(self):
        entry = next(e for e in secrets() if e["name"] == "web-app-openbao")
        values = {"approle_role_id": "r", "approle_secret_id": "s", "seal_key": "k"}
        self.assertEqual(
            fixture.semaphore_fixture_fields(values, entry),
            {"approle_role_id": "r", "approle_secret_id": "s"},
        )
        with self.assertRaises(AnsibleFilterError) as caught:
            fixture.semaphore_fixture_fields({"approle_role_id": "r"}, entry)
        self.assertIn("approle_secret_id", str(caught.exception))
        self.assertNotIn("'r'", str(caught.exception))


class TestFixtureReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = OpenBaoStub(tokens={TOKEN: ["platform/fixture/"]}, logins={})
        cls.addClassCleanup(cls.stub.close)

    def references(self):
        mount = role_vars(ROLE)["SEMAPHORE_DEPLOY_FIXTURE_BAO_MOUNT"]
        return fixture.semaphore_fixture_references(secrets(), mount)

    def test_the_references_hold_no_value_and_parse_as_openbao_references(self):
        built = self.references()
        self.assertEqual(
            built["users"]["platform_administrator"]["password"],
            {
                "openbao": "platform/fixture/platform/users/platform_administrator#password"
            },
        )
        self.assertEqual(
            [
                ".".join(parts)
                for parts, _ in openbao_client.user_references(built["users"])
            ],
            ["users.platform_administrator.password"],
        )
        for application_id, config in built["applications"].items():
            credentials = config["secrets"]["credentials"]
            with self.subTest(application_id=application_id):
                found = dict(openbao_client.references(credentials))
                self.assertEqual(sorted(found), sorted(credentials))

    def test_each_reference_reads_the_kv_v2_entry_the_writer_fills(self):
        for entry in secrets():
            self.stub.put(
                f"platform/{entry['path']}",
                {field: f"value-of-{field}" for field in entry["fields"]},
            )
        client = openbao_client.OpenBaoClient(self.stub.addr, self.stub.cafile, TOKEN)
        built = self.references()
        leaves = [
            *(ref for _, ref in openbao_client.user_references(built["users"])),
            *(
                ref
                for config in built["applications"].values()
                for _, ref in openbao_client.references(
                    config["secrets"]["credentials"]
                )
            ),
        ]
        for reference in leaves:
            with self.subTest(reference=str(reference)):
                self.assertEqual(client.read(reference), f"value-of-{reference.field}")
        self.assertTrue(
            all(
                path.startswith("platform/data/fixture/platform/")
                for method, path, _ in self.stub.requests
                if method == "GET"
            )
        )

    def test_the_references_var_reads_no_credential(self):
        scope = fixture_scope()
        self.assertEqual(
            credential_reads("{{ SEMAPHORE_DEPLOY_FIXTURE_REFERENCES }}", scope), []
        )

    def test_negative_control_a_value_instead_of_a_reference_is_caught(self):
        scope = fixture_scope()
        planted = {
            **scope["SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_CREDENTIALS"],
            "users": ["{{ lookup('users', 'platform_administrator').password }}"],
        }
        scope = {**scope, "SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_CREDENTIALS": planted}
        self.assertNotEqual(
            credential_reads("{{ SEMAPHORE_DEPLOY_FIXTURE_REFERENCES }}", scope), []
        )


class TestFixtureWriter(unittest.TestCase):
    def test_the_writer_converges_through_the_kv_helper_below_the_root(self):
        tasks = list(_tasks(load_yaml_any(str(WRITER))))
        self.assertEqual(len(tasks), 3)
        for task, kind in zip(tasks[:2], ("users", "apps"), strict=True):
            with self.subTest(kind=kind):
                include = task["ansible.builtin.include_role"]
                self.assertEqual(
                    (include["name"], include["tasks_from"]),
                    ("web-app-openbao", "utils/kv.yml"),
                )
                variables = task["vars"]
                self.assertEqual(variables["openbao_kv_state"], "present")
                self.assertEqual(
                    variables["openbao_kv_mount"],
                    "{{ SEMAPHORE_DEPLOY_FIXTURE_BAO_MOUNT }}",
                )
                self.assertEqual(
                    variables["openbao_kv_path"], "{{ semaphore_fixture_secret.path }}"
                )
                self.assertIn(f"'{kind}'", task["loop"])
        workspace_key = tasks[2]["vars"]
        self.assertEqual(
            (workspace_key["openbao_kv_state"], workspace_key["openbao_kv_path"]),
            ("present", "{{ SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH }}"),
        )
        kv = list(_tasks(load_yaml_any(str(OPENBAO / "tasks" / "utils" / "kv.yml"))))
        write = next(task for task in kv if "Write" in task["name"])
        self.assertIn("openbao_kv_current != openbao_kv_data", write["when"])

    def test_the_writer_root_lies_below_the_reader_policy(self):
        semaphore, openbao = role_vars(ROLE), role_vars(OPENBAO)
        self.assertEqual(
            semaphore["SEMAPHORE_DEPLOY_FIXTURE_BAO_MOUNT"],
            openbao["OPENBAO_PLATFORM_MOUNT"],
        )
        self.assertTrue(
            semaphore["SEMAPHORE_DEPLOY_FIXTURE_BAO_ROOT"].startswith(
                openbao["OPENBAO_FIXTURE_PREFIX"] + "/"
            )
        )
        self.assertEqual(
            semaphore["SEMAPHORE_WORKSPACES_FIXTURE_BAO_ROLE"],
            openbao["OPENBAO_FIXTURE_ROLE"],
        )

    def test_everything_but_the_resolver_waits_for_the_fixture(self):
        include = next(
            task
            for task in gated_tasks(load_yaml_any(str(INPUTS)))
            if "fixture/credentials.yml"
            in str(task.get("ansible.builtin.include_tasks"))
        )
        self.assertIn("SEMAPHORE_DEPLOY_FIXTURE_ENABLED | bool", include["when"])
        reader = next(
            task
            for task in _tasks(load_yaml_any(str(IDENTITY)))
            if "semaphore_fixture_reader_identity"
            in (task.get("ansible.builtin.set_fact") or {})
        )
        self.assertEqual(reader["when"], "SEMAPHORE_DEPLOY_FIXTURE_ENABLED | bool")
        role = role_vars(ROLE)["SEMAPHORE_WORKSPACES_VARIABLES"]["BAO_FIXTURE_ROLE"]
        template = environment().from_string(role)
        for enabled, expected in ((True, "workspace-fixture"), (False, "")):
            with self.subTest(enabled=enabled):
                self.assertEqual(
                    template.render(
                        SEMAPHORE_WORKSPACES_FIXTURE_BAO_ROLE="workspace-fixture",
                        SEMAPHORE_DEPLOY_FIXTURE_ENABLED=enabled,
                    ),
                    expected,
                )


class TestTheReaderIdentity(unittest.TestCase):
    def test_the_reader_binds_the_workspace_template_of_the_workspaces_project(self):
        task = next(
            task
            for task in _tasks(load_yaml_any(str(IDENTITY)))
            if "semaphore_fixture_reader_identity"
            in (task.get("ansible.builtin.set_fact") or {})
        )
        identity = task["ansible.builtin.set_fact"]["semaphore_fixture_reader_identity"]
        jinja = environment()
        workspaces = {
            "project_id": 3,
            "templates": {
                "workspace": {"template_id": 30},
                "members": {"template_id": 31},
            },
        }
        rendered = {
            key: jinja.from_string(value).render(
                semaphore_workspaces_identity=workspaces
            )
            for key, value in identity.items()
        }
        self.assertEqual(rendered, {"project_id": "3", "template_id": "30"})


if __name__ == "__main__":
    unittest.main()
