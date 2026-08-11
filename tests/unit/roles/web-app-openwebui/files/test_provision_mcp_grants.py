from __future__ import annotations

import asyncio
import importlib.util
import json
import unittest
from copy import deepcopy
from typing import ClassVar
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-openwebui/files/provision_mcp_grants.py"


def load_script(
    groups: dict, members: dict | None = None, declared: list | None = None
) -> object:
    spec = importlib.util.spec_from_file_location("provision_mcp_grants", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "os.environ",
        {
            "OPENWEBUI_BASE": "http://localhost:8080",
            "OPENWEBUI_MCP_GROUPS": json.dumps(groups),
            "OPENWEBUI_MCP_MEMBERS": json.dumps(members or {}),
            "OPENWEBUI_MCP_CONNECTIONS": json.dumps(declared or []),
            "OPENWEBUI_ADMIN_EMAIL": "administrator@example.org",
            "OPENWEBUI_ADMIN_PASSWORD": "x" * 32,
        },
    ):
        spec.loader.exec_module(module)
    return module


class FakeUser:
    def __init__(self, user_id, role, email="", name=""):
        self.id = user_id
        self.role = role
        self.email = email
        self.name = name


class FakeBackend:
    """Stands in for the open_webui models the script imports in-process."""

    def __init__(self, users, keys=None):
        self.users = list(users)
        self.keys = dict(keys or {})
        self.created = []
        self.deleted = []

    def install(self, monkey):
        import types

        users = types.SimpleNamespace(
            get_users=self._get_users,
            get_user_api_key_by_id=self._get_key,
            update_user_api_key_by_id=self._set_key,
            delete_user_api_key_by_id=self._delete_key,
        )
        auths = types.SimpleNamespace(insert_new_auth=self._insert_auth)
        for name, attr, value in (
            ("open_webui.models.users", "Users", users),
            ("open_webui.models.auths", "Auths", auths),
            ("open_webui.utils.auth", "get_password_hash", self._hash),
        ):
            module = types.ModuleType(name)
            setattr(module, attr, value)
            monkey[name] = module

    async def _get_users(self):
        return {"users": self.users, "total": len(self.users)}

    async def _get_key(self, user_id):
        return self.keys.get(user_id)

    async def _set_key(self, user_id, key):
        self.keys[user_id] = key
        return True

    async def _delete_key(self, user_id):
        self.deleted.append(user_id)
        self.keys.pop(user_id, None)
        return True

    async def _insert_auth(self, email, password, name, role):
        created = FakeUser(f"created-{email}", role)
        self.created.append(created)
        self.users.append(created)
        return created

    async def _hash(self, password):
        return f"hashed-{password}"


class FakeApi:
    """Minimal stand-in for the Open WebUI admin API used by the script."""

    def __init__(self, connections, groups=(), duplicate=False):
        self.connections = deepcopy(connections)
        self.groups = [{"id": f"id-{name}", "name": name} for name in groups]
        if duplicate and self.groups:
            self.groups.append(dict(self.groups[0]))
        self.writes = 0
        self.member_writes = 0

    def __call__(self, path, key, payload=None):
        if path == "/api/v1/groups/" and payload is None:
            return 200, self.groups
        if path == "/api/v1/groups/create":
            created = {"id": f"id-{payload['name']}", "name": payload["name"]}
            self.groups.append(created)
            return 200, created
        if path == "/api/v1/configs/tool_servers" and payload is None:
            return 200, {"TOOL_SERVER_CONNECTIONS": deepcopy(self.connections)}
        if path == "/api/v1/configs/tool_servers":
            self.writes += 1
            self.connections = deepcopy(payload["TOOL_SERVER_CONNECTIONS"])
            return 200, None
        if path.startswith("/api/v1/groups/id/") and path.endswith("/update"):
            group_id = path[len("/api/v1/groups/id/") : -len("/update")]
            for group in self.groups:
                if group["id"] == group_id:
                    group["user_ids"] = list(payload["user_ids"])
                    self.member_writes += 1
                    return 200, group
            raise AssertionError(f"update of unknown group {group_id}")
        raise AssertionError(f"unexpected call to {path}")


def connection(server_id, kind="mcp"):
    return {
        "url": f"http://{server_id}/mcp",
        "type": kind,
        "auth_type": "bearer",
        "key": "secret",
        "config": {"enable": False, "access_grants": []},
        "info": {"id": server_id, "name": server_id},
    }


class TestDeclaredSetIsRegistered(unittest.TestCase):
    """A provider that becomes reachable after the first run must still arrive.

    Open WebUI keeps the tool servers in its own config, so a deployment that
    already holds connections answers every later read with them. Reading that
    answer as the desired state leaves a newly declared provider registered
    nowhere, with nothing failing.
    """

    GROUPS: ClassVar[dict] = {
        "web-app-baserow": "/roles/web-app-baserow/mcp",
        "svc-db-qdrant": "/roles/svc-db-qdrant/mcp",
    }

    def test_a_newly_declared_provider_is_added(self) -> None:
        module = load_script(self.GROUPS, declared=[connection("svc-db-qdrant")])
        api = FakeApi([connection("web-app-baserow")])

        with patch.object(module, "call", api):
            granted, changed = module.grant("sk-test")

        self.assertTrue(changed)
        self.assertEqual(
            ["svc-db-qdrant", "web-app-baserow"],
            sorted(c["info"]["id"] for c in api.connections),
        )
        self.assertEqual(["svc-db-qdrant", "web-app-baserow"], sorted(granted))

    def test_an_already_registered_provider_is_not_duplicated(self) -> None:
        module = load_script(self.GROUPS, declared=[connection("web-app-baserow")])
        api = FakeApi([connection("web-app-baserow")])

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(
            ["web-app-baserow"], [c["info"]["id"] for c in api.connections]
        )

    def test_a_rotated_bearer_replaces_the_registered_one(self) -> None:
        rotated = connection("web-app-baserow")
        rotated["key"] = "rotated"
        module = load_script(self.GROUPS, declared=[rotated])
        api = FakeApi([connection("web-app-baserow")])

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(
            ["rotated"],
            [c["key"] for c in api.connections if c["info"]["id"] == "web-app-baserow"],
            "a client left holding the old bearer keeps a credential the provider "
            "has already rejected, and nothing reports it",
        )

    def test_a_moved_endpoint_replaces_the_registered_url(self) -> None:
        moved = connection("web-app-baserow")
        moved["url"] = "http://baserow:80/mcp/moved/sse"
        module = load_script(self.GROUPS, declared=[moved])
        api = FakeApi([connection("web-app-baserow")])

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(
            ["http://baserow:80/mcp/moved/sse"],
            [c["url"] for c in api.connections if c["info"]["id"] == "web-app-baserow"],
        )

    def test_an_undeclared_connection_keeps_its_own_endpoint(self) -> None:
        module = load_script(self.GROUPS, declared=[connection("web-app-baserow")])
        api = FakeApi([connection("web-app-homeassistant")])

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(
            ["http://web-app-homeassistant/mcp"],
            [
                c["url"]
                for c in api.connections
                if c["info"]["id"] == "web-app-homeassistant"
            ],
        )

    def test_a_connection_the_operator_added_survives(self) -> None:
        module = load_script(self.GROUPS, declared=[connection("svc-db-qdrant")])
        api = FakeApi([connection("some-openapi-server", kind="openapi")])

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertIn("some-openapi-server", [c["info"]["id"] for c in api.connections])


class TestProvisionMcpGrants(unittest.TestCase):
    def test_only_mapped_mcp_connections_get_a_group_grant(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi(
            [
                connection("web-app-baserow"),
                connection("web-app-homeassistant"),
                connection("some-openapi-server", kind="openapi"),
            ]
        )

        with patch.object(module, "call", api):
            granted, changed = module.grant("sk-test")

        self.assertEqual(["web-app-baserow"], sorted(granted))
        self.assertTrue(changed)
        by_id = {c["info"]["id"]: c for c in api.connections}
        self.assertEqual(
            [
                {
                    "principal_type": "group",
                    "principal_id": "id-/roles/web-app-baserow/mcp",
                    "permission": "read",
                }
            ],
            by_id["web-app-baserow"]["config"]["access_grants"],
        )
        self.assertEqual([], by_id["web-app-homeassistant"]["config"]["access_grants"])
        self.assertEqual([], by_id["some-openapi-server"]["config"]["access_grants"])

    def test_a_server_is_enabled_only_together_with_its_grant(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi(
            [connection("web-app-baserow"), connection("web-app-homeassistant")]
        )

        with patch.object(module, "call", api):
            module.grant("sk-test")

        by_id = {c["info"]["id"]: c for c in api.connections}
        self.assertTrue(by_id["web-app-baserow"]["config"]["enable"])
        self.assertFalse(
            by_id["web-app-homeassistant"]["config"]["enable"],
            "an ungranted server must stay disabled; an enabled one with empty grants "
            "is reachable by every administrator",
        )

    def test_a_second_run_writes_nothing(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi([connection("web-app-baserow")])

        with patch.object(module, "call", api):
            module.grant("sk-test")
            writes_after_first = api.writes
            granted, changed = module.grant("sk-test")

        self.assertEqual(["web-app-baserow"], sorted(granted))
        self.assertFalse(changed)
        self.assertEqual(writes_after_first, api.writes)

    def test_an_existing_group_is_reused_instead_of_recreated(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi(
            [connection("web-app-baserow")], groups=["/roles/web-app-baserow/mcp"]
        )

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(1, len(api.groups))

    def test_a_group_that_lost_its_last_member_is_emptied(self) -> None:
        module = load_script(
            {"web-app-baserow": "/roles/web-app-baserow/mcp"}, members={}
        )
        api = FakeApi(
            [connection("web-app-baserow")], groups=["/roles/web-app-baserow/mcp"]
        )
        api.groups[0]["user_ids"] = ["stale-user"]

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual([], api.groups[0]["user_ids"])
        self.assertEqual(1, api.member_writes)

    def _grant_with_members(self, members, known_users):
        module = load_script(
            {"web-app-baserow": "/roles/web-app-baserow/mcp"}, members=members
        )
        api = FakeApi(
            [connection("web-app-baserow")], groups=["/roles/web-app-baserow/mcp"]
        )
        api.groups[0]["user_ids"] = []
        backend = FakeBackend(known_users)
        modules = {}
        backend.install(modules)

        with patch.dict("sys.modules", modules), patch.object(module, "call", api):
            module.grant("sk-test")
        return api

    def test_a_declared_member_is_written_into_its_group(self) -> None:
        api = self._grant_with_members(
            {"web-app-baserow": [{"username": "biber", "email": "biber@example.org"}]},
            [FakeUser("u-biber", "user", email="biber@example.org", name="Biber")],
        )

        self.assertEqual(["u-biber"], api.groups[0]["user_ids"])
        self.assertEqual(1, api.member_writes)

    def test_a_member_is_matched_by_username_when_the_email_differs(self) -> None:
        api = self._grant_with_members(
            {"web-app-baserow": [{"username": "biber", "email": "unused@example.org"}]},
            [FakeUser("u-biber", "user", email="other@example.org", name="biber")],
        )

        self.assertEqual(["u-biber"], api.groups[0]["user_ids"])

    def test_the_filter_that_renders_members_produces_what_this_script_consumes(
        self,
    ) -> None:
        mcp_group_members = importlib.import_module(
            "plugins.filter.mcp.group_members"
        ).mcp_group_members
        members = mcp_group_members(
            {
                "biber": {
                    "username": "biber",
                    "email": "biber@example.org",
                    "application_roles": {"web-app-baserow": ["mcp"]},
                }
            },
            [{"id": "web-app-baserow"}],
            "mcp-reader",
        )

        api = self._grant_with_members(
            json.loads(json.dumps(members)),
            [FakeUser("u-biber", "user", email="biber@example.org", name="Biber")],
        )

        self.assertEqual(["u-biber"], api.groups[0]["user_ids"])

    def test_a_member_openwebui_never_saw_is_skipped(self) -> None:
        api = self._grant_with_members(
            {"web-app-baserow": [{"username": "biber", "email": "biber@example.org"}]},
            [FakeUser("u-other", "user", email="other@example.org", name="other")],
        )

        self.assertEqual([], api.groups[0]["user_ids"])
        self.assertEqual(
            0,
            api.member_writes,
            "a member who has never signed in must not trigger a write; the group "
            "already matches the resolvable member set",
        )

    def test_a_group_already_matching_its_members_is_left_alone(self) -> None:
        module = load_script(
            {"web-app-baserow": "/roles/web-app-baserow/mcp"}, members={}
        )
        api = FakeApi(
            [connection("web-app-baserow")], groups=["/roles/web-app-baserow/mcp"]
        )
        api.groups[0]["user_ids"] = []

        with patch.object(module, "call", api):
            module.grant("sk-test")

        self.assertEqual(0, api.member_writes)

    def test_two_groups_of_one_name_abort_rather_than_guess(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi(
            [connection("web-app-baserow")],
            groups=["/roles/web-app-baserow/mcp"],
            duplicate=True,
        )

        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.grant("sk-test")

        self.assertIn("refusing to guess", str(exit_.exception))

    def test_a_write_that_loses_a_connection_aborts(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi([connection("web-app-baserow"), connection("web-app-jenkins")])

        def losing_call(path, key, payload=None):
            if path == "/api/v1/configs/tool_servers" and payload is not None:
                payload = {
                    "TOOL_SERVER_CONNECTIONS": payload["TOOL_SERVER_CONNECTIONS"][:1]
                }
            return api(path, key, payload)

        with (
            patch.object(module, "call", losing_call),
            self.assertRaises(SystemExit) as exit_,
        ):
            module.grant("sk-test")

        self.assertIn("the write lost ['web-app-jenkins']", str(exit_.exception))

    def test_a_write_the_server_ignores_aborts(self) -> None:
        module = load_script({"web-app-baserow": "/roles/web-app-baserow/mcp"})
        api = FakeApi([connection("web-app-baserow")])

        def ignoring_call(path, key, payload=None):
            if path == "/api/v1/configs/tool_servers" and payload is not None:
                return 200, None
            return api(path, key, payload)

        with (
            patch.object(module, "call", ignoring_call),
            self.assertRaises(SystemExit) as exit_,
        ):
            module.grant("sk-test")

        self.assertIn("instead of one group grant", str(exit_.exception))


class TestResolveApiKey(unittest.TestCase):
    def _resolve(self, backend):
        module = load_script({})
        modules = {}
        backend.install(modules)
        with patch.dict("sys.modules", modules):
            return module, asyncio.run(module.resolve_api_key())

    def test_an_existing_administrator_key_is_reused_and_kept(self) -> None:
        backend = FakeBackend(
            [FakeUser("u1", "user"), FakeUser("admin1", "admin")],
            keys={"admin1": "sk-operator"},
        )

        _module, (user_id, key, minted) = self._resolve(backend)

        self.assertEqual("admin1", user_id)
        self.assertEqual("sk-operator", key)
        self.assertFalse(minted, "an operator's own key must not be reported as minted")
        self.assertEqual([], backend.created)

    def test_a_missing_key_is_minted_and_marked_for_removal(self) -> None:
        backend = FakeBackend([FakeUser("admin1", "admin")])

        _module, (user_id, key, minted) = self._resolve(backend)

        self.assertEqual("admin1", user_id)
        self.assertTrue(key.startswith("sk-"))
        self.assertTrue(minted)
        self.assertEqual(key, backend.keys["admin1"])

    def test_an_instance_without_users_gets_one_administrator(self) -> None:
        backend = FakeBackend([])

        _module, (user_id, _key, minted) = self._resolve(backend)

        self.assertEqual(["admin"], [user.role for user in backend.created])
        self.assertEqual(backend.created[0].id, user_id)
        self.assertTrue(minted)

    def test_a_minted_key_is_dropped_even_when_granting_fails(self) -> None:
        backend = FakeBackend([FakeUser("admin1", "admin")])
        module = load_script({})
        modules = {}
        backend.install(modules)

        def exploding_grant(_key):
            raise RuntimeError("boom")

        with patch.dict("sys.modules", modules):
            admin_id, _key, minted = asyncio.run(module.resolve_api_key())
            self.assertTrue(minted)
            try:
                exploding_grant(_key)
            except RuntimeError:
                pass
            finally:
                asyncio.run(module.drop_api_key(admin_id))

        self.assertEqual(["admin1"], backend.deleted)
        self.assertNotIn("admin1", backend.keys)


if __name__ == "__main__":
    unittest.main()
