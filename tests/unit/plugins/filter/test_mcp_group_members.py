"""Unit tests for ``plugins/filter/mcp/group_members.py``."""

import importlib
import unittest

mcp_group_members = importlib.import_module(
    "plugins.filter.mcp.group_members"
).mcp_group_members

SERVERS = [{"id": "web-app-baserow"}, {"id": "web-app-zammad"}]
READER_ROLE = "mcp-reader"
WRITER_ROLE = "mcp-writer"


class TestMcpGroupMembers(unittest.TestCase):
    def test_no_servers_yields_no_groups(self):
        self.assertEqual(mcp_group_members({"alice": {}}, [], READER_ROLE), {})

    def test_grant_lands_only_on_the_named_application(self):
        users = {
            "alice": {
                "username": "alice",
                "email": "alice@example.org",
                "application_roles": {"web-app-baserow": ["mcp"]},
            }
        }
        self.assertEqual(
            mcp_group_members(users, SERVERS, READER_ROLE),
            {
                "web-app-baserow": [
                    {"username": "alice", "email": "alice@example.org"}
                ],
                "web-app-zammad": [],
            },
        )

    def test_unscoped_mcp_role_grants_nothing(self):
        users = {"alice": {"username": "alice", "roles": ["mcp"]}}
        self.assertEqual(
            mcp_group_members(users, SERVERS, READER_ROLE),
            {"web-app-baserow": [], "web-app-zammad": []},
        )

    def test_removing_the_last_grant_empties_the_group(self):
        self.assertEqual(
            mcp_group_members({"alice": {"username": "alice"}}, SERVERS, READER_ROLE),
            {"web-app-baserow": [], "web-app-zammad": []},
        )

    def test_members_are_sorted_and_use_the_username_attribute(self):
        users = {
            "b-key": {
                "username": "zoe",
                "email": "zoe@example.org",
                "application_roles": {"web-app-baserow": ["mcp"]},
            },
            "a-key": {
                "username": "amy",
                "email": "amy@example.org",
                "application_roles": {"web-app-baserow": ["mcp"]},
            },
        }
        self.assertEqual(
            [
                m["username"]
                for m in mcp_group_members(users, SERVERS, READER_ROLE)[
                    "web-app-baserow"
                ]
            ],
            ["amy", "zoe"],
        )

    def test_a_member_without_an_email_still_carries_its_username(self):
        users = {
            "alice": {
                "username": "alice",
                "application_roles": {"web-app-baserow": ["mcp"]},
            }
        }
        self.assertEqual(
            mcp_group_members(users, SERVERS, READER_ROLE)["web-app-baserow"],
            [{"username": "alice", "email": ""}],
        )

    def test_servers_without_an_id_are_skipped(self):
        self.assertEqual(mcp_group_members({}, [{"url": "http://x"}], READER_ROLE), {})

    def test_writer_members_are_resolved_separately(self):
        users = {
            "alice": {
                "application_roles": {"web-app-baserow": [WRITER_ROLE]},
            }
        }
        self.assertEqual(
            [{"username": "alice", "email": ""}],
            mcp_group_members(users, SERVERS, WRITER_ROLE)["web-app-baserow"],
        )

    def test_unknown_role_fails(self):
        with self.assertRaisesRegex(ValueError, "unknown role"):
            mcp_group_members({}, SERVERS, "administrator")


if __name__ == "__main__":
    unittest.main()
