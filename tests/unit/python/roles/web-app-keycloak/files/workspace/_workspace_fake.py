from __future__ import annotations

import copy
import itertools
import sys
import urllib.parse
import uuid

from utils.cache.files import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

from keycloak_admin import KeycloakHTTPError

WORKSPACES_CLIENT = "workspaces"
WORKSPACES_UUID = "c-workspaces"
WRITES = ("POST", "PUT", "DELETE")
KINDS = ("org", "grp", "role", "inv", "user")
UNAVAILABLE = 503
WS = "0f1e2d3c-4b5a-4968-8776-655443322110"
OTHER_WS = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
OWNER = "11111111-1111-4111-8111-111111111111"
STAFF = "22222222-2222-4222-8222-222222222222"
MANAGED = "33333333-3333-4333-8333-333333333333"
CUSTOMER = "44444444-4444-4444-8444-444444444444"
USERS = {
    OWNER: {
        "id": OWNER,
        "username": "owner",
        "email": "owner@example.com",
        "enabled": True,
    },
    STAFF: {
        "id": STAFF,
        "username": "staff",
        "email": "staff@example.com",
        "enabled": True,
        "groups": ["/roles/web-app-semaphore/operator"],
    },
    MANAGED: {
        "id": MANAGED,
        "username": "managed",
        "email": "managed@example.com",
        "enabled": True,
    },
    CUSTOMER: {
        "id": CUSTOMER,
        "username": "customer",
        "email": "customer@example.com",
        "enabled": True,
    },
}
ROOT = "/roles"
SIGN_IN = "/roles/web-app-semaphore/user"


def realm_group_id(path: str) -> str:
    """
    Args:
        path: the path of a realm group.

    Returns:
        The id the fake gives that group, the same on every call.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, path))


def state(fake: FakeKeycloak) -> dict:
    """
    Args:
        fake: the fake Keycloak.

    Returns:
        Everything a workspace task may change, for before and after comparisons.
    """
    return copy.deepcopy(
        {
            "orgs": fake.orgs,
            "groups": fake.org_groups,
            "memberships": fake.memberships,
            "group_members": fake.group_members,
            "invitations": fake.invitations,
            "roles": fake.client_roles,
            "users": fake.users,
        }
    )


class FakeKeycloak:
    """
    Args:
        users: user representations by id; each may carry ``groups``, the
            paths of its realm groups.
    """

    def __init__(self, users: dict[str, dict]) -> None:
        self.users = copy.deepcopy(users)
        self.orgs: dict[str, dict] = {}
        self.org_groups: dict[str, dict[str, dict]] = {}
        self.memberships: dict[str, dict[str, str]] = {}
        self.group_members: dict[str, set[str]] = {}
        self.invitations: dict[str, dict[str, dict]] = {}
        self.client_roles: dict[str, dict] = {}
        self.writes: list[tuple[str, str, object]] = []
        self.reads: list[str] = []
        self.mails: list[tuple[str, str, str]] = []
        self.fail_at: int | None = None
        self.params: dict[str, str] = {}
        self._ids = itertools.count(1)

    def new_id(self, kind: str) -> str:
        """
        Args:
            kind: the kind of object, which picks the id's leading digit.

        Returns:
            A fresh lowercase UUID.
        """
        prefix = KINDS.index(kind) + 1
        return str(uuid.UUID(int=(prefix << 120) + next(self._ids)))

    def plant_org(self, name: str, attributes: dict) -> str:
        """
        Args:
            name: name and alias.
            attributes: the organization's attributes.

        Returns:
            The organization id.
        """
        org_id = self.new_id("org")
        self.orgs[org_id] = {
            "id": org_id,
            "name": name,
            "alias": name,
            "enabled": True,
            "attributes": copy.deepcopy(attributes),
        }
        self.org_groups[org_id] = {}
        self.memberships[org_id] = {}
        self.invitations[org_id] = {}
        return org_id

    def fail(self, method: str, path: str, status: int) -> None:
        raise KeycloakHTTPError(method, path, status)

    def _write(self, method: str, path: str, payload: object) -> None:
        if self.fail_at is not None and len(self.writes) == self.fail_at:
            self.fail_at = None
            self.fail(method, path, UNAVAILABLE)
        self.writes.append((method, path, copy.deepcopy(payload)))

    def submit(self, path: str, fields: dict) -> tuple[object, str]:
        route, _, query = path.partition("?")
        self._write("POST", route, {**fields, "query": query})
        parts = route.split("/")
        org_id = parts[1]
        email = fields["email"].strip().lower()
        client = urllib.parse.parse_qs(query).get("client_id", [""])[0]
        held = [
            i
            for i in self.invitations[org_id].values()
            if i["email"] == email and i["status"] == "PENDING"
        ]
        if held:
            self.fail("POST", route, 409)
        invitation_id = self.new_id("inv")
        self.invitations[org_id][invitation_id] = {
            "id": invitation_id,
            "email": email,
            "status": "PENDING",
        }
        self.mails.append((org_id, email, client))
        return None, ""

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        self.params = params
        if method in WRITES:
            self._write(method, route, payload)
        else:
            self.reads.append(path)
        parts = route.split("/")
        handler = getattr(self, f"_{parts[0]}")
        return handler(method, parts, params, payload, route)

    def _clients(self, method, parts, params, payload, route):
        if len(parts) == 1:
            wanted = params["clientId"]
            found = [{"id": WORKSPACES_UUID, "clientId": WORKSPACES_CLIENT}]
            return [c for c in found if c["clientId"] == wanted], ""
        if len(parts) == 3 and method == "POST":
            role = {"id": self.new_id("role"), "name": payload["name"]}
            self.client_roles[payload["name"]] = role
            return None, role["id"]
        name = urllib.parse.unquote(parts[3])
        if name not in self.client_roles:
            self.fail(method, route, 404)
        if method == "DELETE":
            del self.client_roles[name]
            return None, ""
        return copy.deepcopy(self.client_roles[name]), ""

    def _users(self, method, parts, params, payload, route):
        if len(parts) == 1:
            found = [
                u for u in self.users.values() if u["username"] == params["username"]
            ]
            return copy.deepcopy(found), ""
        user_id = parts[1]
        if user_id not in self.users:
            self.fail(method, route, 404)
        held = self.users[user_id].get("groups", [])
        if len(parts) == 3:
            return [{"id": realm_group_id(p), "path": p} for p in held], ""
        if len(parts) == 4 and method == "DELETE":
            self.users[user_id]["groups"] = [
                p for p in held if realm_group_id(p) != parts[3]
            ]
            return None, ""
        if method == "DELETE":
            del self.users[user_id]
            for members in self.memberships.values():
                members.pop(user_id, None)
            return None, ""
        return copy.deepcopy(self.users[user_id]), ""

    def _organizations(self, method, parts, params, payload, route):
        if len(parts) == 1 and method == "POST":
            return self._create_org(payload, route)
        if len(parts) == 1:
            return self._search_orgs(params), ""
        if parts[1] == "members":
            return self._orgs_of(parts[2]), ""
        org_id = parts[1]
        if org_id not in self.orgs:
            self.fail(method, route, 404)
        if len(parts) == 2:
            return self._org(method, org_id, payload)
        handler = getattr(self, f"_org_{parts[2].replace('-', '_')}")
        return handler(method, org_id, parts[3:], payload, route)

    def _create_org(self, payload, route):
        taken = {o["alias"] for o in self.orgs.values()} | {
            o["name"] for o in self.orgs.values()
        }
        if payload["alias"] in taken or payload["name"] in taken:
            self.fail("POST", route, 409)
        org_id = self.plant_org(payload["name"], payload.get("attributes") or {})
        return None, org_id

    def _search_orgs(self, params):
        key, _, value = params["q"].partition(":")
        found = [
            copy.deepcopy(o)
            for o in self.orgs.values()
            if value in o["attributes"].get(key, [])
        ]
        return found[: int(params["max"])]

    def _orgs_of(self, user_id):
        return [
            copy.deepcopy(self.orgs[org_id])
            for org_id, members in self.memberships.items()
            if user_id in members
        ]

    def _org(self, method, org_id, payload):
        if method == "DELETE":
            for group in self.org_groups.pop(org_id).values():
                self.group_members.pop(group["id"], None)
            del self.orgs[org_id]
            self.memberships.pop(org_id)
            return None, ""
        if method == "PUT":
            self.orgs[org_id] = copy.deepcopy(payload)
            return None, ""
        return copy.deepcopy(self.orgs[org_id]), ""

    def _org_groups(self, method, org_id, rest, payload, route):
        groups = self.org_groups[org_id]
        if not rest and method == "POST":
            group_id = self.new_id("grp")
            groups[group_id] = {
                "id": group_id,
                "name": payload["name"],
                "clientRoles": {},
            }
            self.group_members[group_id] = set()
            return None, group_id
        if not rest:
            return copy.deepcopy(list(groups.values())), ""
        group = groups[rest[0]]
        if rest[1] == "role-mappings":
            mapped = group["clientRoles"].setdefault(WORKSPACES_CLIENT, [])
            mapped.extend(role["name"] for role in payload)
            return None, ""
        members = self.group_members[group["id"]]
        if len(rest) == 2:
            return [copy.deepcopy(self.users[u]) for u in sorted(members)], ""
        return self._group_member(method, org_id, members, rest[2], route)

    def _group_member(self, method, org_id, members, user_id, route):
        if method == "PUT":
            if user_id not in self.memberships[org_id]:
                self.fail(method, route, 400)
            if user_id in members:
                self.fail(method, route, 409)
            members.add(user_id)
            return None, ""
        if user_id not in members:
            self.fail(method, route, 400)
        members.discard(user_id)
        return None, ""

    def _org_members(self, method, org_id, rest, payload, route):
        members = self.memberships[org_id]
        if not rest and method == "POST":
            user_id = str(payload)
            if user_id not in self.users:
                self.fail(method, route, 404)
            if user_id in members:
                self.fail(method, route, 409)
            members[user_id] = "UNMANAGED"
            return None, user_id
        if not rest:
            return [
                {**copy.deepcopy(self.users[u]), "membershipType": kind}
                for u, kind in sorted(members.items())
            ], ""
        user_id = rest[0]
        if user_id not in members:
            self.fail(method, route, 400 if method == "DELETE" else 404)
        if method == "DELETE":
            del members[user_id]
            for group in self.org_groups[org_id].values():
                self.group_members[group["id"]].discard(user_id)
            return None, ""
        return copy.deepcopy(self.users[user_id]), ""

    def _org_invitations(self, method, org_id, rest, payload, route):
        held = self.invitations[org_id]
        if rest and method == "DELETE":
            if rest[0] not in held:
                self.fail(method, route, 404)
            del held[rest[0]]
            return None, ""
        return self.invitations_of(org_id, self.params), ""

    def invitations_of(self, org_id: str, params: dict) -> list[dict]:
        """
        Args:
            org_id: the organization.
            params: the email and status filters.

        Returns:
            The matching invitations.
        """
        return [
            copy.deepcopy(i)
            for i in self.invitations[org_id].values()
            if all(i[k] == v for k, v in params.items() if k in ("email", "status"))
        ]

    def accept(self, org_id: str, email: str) -> str:
        """
        Args:
            org_id: the organization.
            email: the invited address.

        Returns:
            The id of the user who accepted, now a member without a role group.
        """
        held = self.invitations[org_id]
        invitation_id = next(i for i, inv in held.items() if inv["email"] == email)
        del held[invitation_id]
        user_id = next(
            (u for u, user in self.users.items() if user["email"] == email), None
        )
        if user_id is None:
            user_id = self.new_id("user")
            self.users[user_id] = {
                "id": user_id,
                "username": email.split("@", maxsplit=1)[0],
                "email": email,
                "enabled": True,
            }
        self.memberships[org_id][user_id] = "UNMANAGED"
        return user_id
