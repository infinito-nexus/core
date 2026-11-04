"""In-memory stand-in for the slice of Frappe the ``infinito_rbac`` app calls.

``login_oauth_user`` behaves like Frappe 16's: it takes the account named after
the sign-in's e-mail address, refuses a missing one because the Social Login Key
denies sign-ups, refuses a disabled one, and links an enabled one to the
signing-in user when it has no ``keycloak`` row yet.
"""

from __future__ import annotations

import copy
import json
from types import ModuleType, SimpleNamespace


class FrappeValidationError(Exception):
    pass


class FrappePermissionError(Exception):
    pass


class FakeUser:
    def __init__(self, frappe, values):
        object.__setattr__(self, "_frappe", frappe)
        object.__setattr__(self, "flags", SimpleNamespace())
        object.__setattr__(
            self, "_values", {"roles": [], "social_logins": [], **values}
        )

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._values.get(name)

    def __setattr__(self, name, value):
        self._values[name] = value

    def get(self, name):
        return self._values.get(name)

    def add_roles(self, *roles):
        held = {row.role for row in self._values["roles"]}
        self._values["roles"].extend(
            SimpleNamespace(role=role) for role in roles if role not in held
        )
        self.save()

    def remove_roles(self, *roles):
        self._values["roles"] = [
            row for row in self._values["roles"] if row.role not in roles
        ]
        self.save()

    def insert(self):
        self._values["name"] = self._values["email"]
        return self.save()

    def save(self):
        self._frappe.saves.append(
            (self._values["name"], getattr(self.flags, "ignore_permissions", False))
        )
        self._frappe.records[self._values["name"]] = copy.deepcopy(self._values)
        return self


class FakeDb:
    def __init__(self, frappe):
        self._frappe = frappe
        self.committed = False

    def exists(self, doctype, name):
        self._frappe.lookups.append((doctype, name))
        return doctype == "User" and name in self._frappe.records

    def get_value(self, doctype, name, fieldname):
        self._frappe.lookups.append((doctype, name))
        assert doctype == "Social Login Key"
        record = self._frappe.social_login_keys.get(name)
        return record.get(fieldname) if record else None

    def commit(self):
        self.committed = True


def _matches(row, filters):
    for field, expected in filters.items():
        if isinstance(expected, list):
            operator, operand = expected
            assert operator == "in"
            if row[field] not in operand:
                return False
        elif row[field] != expected:
            return False
    return True


class FakeFrappe:
    PermissionError = FrappePermissionError

    def __init__(self):
        self.records = {}
        self.saves = []
        self.social_login_keys = {
            "keycloak": {"user_id_property": "preferred_username"}
        }
        self.conf = {}
        self.userinfo = {}
        self.whitelisted = {}
        self.logged = []
        self.lookups = []
        self.exchanges = []
        self.handovers = []
        self.upstream_custom = []
        self.request = SimpleNamespace(
            path="/api/method/frappe.integrations.oauth2_logins.login_via_keycloak/keycloak"
        )
        self.db = FakeDb(self)

    def seed(self, name, *links, **values):
        """Store an account.

        Args:
            name: the account's name, its e-mail address.
            links: ``(provider, userid)`` of each ``User Social Login`` row.
            values: the account's other fields.
        """
        self.records[name] = {
            "roles": [],
            **values,
            "social_logins": [
                SimpleNamespace(provider=provider, userid=userid)
                for provider, userid in links
            ],
            "name": name,
        }

    def links(self, name):
        return [
            (row.provider, row.userid) for row in self.records[name]["social_logins"]
        ]

    def get_doc(self, doctype, name):
        self.lookups.append((doctype, name))
        assert doctype == "User"
        return FakeUser(self, copy.deepcopy(self.records[name]))

    def new_doc(self, doctype):
        assert doctype == "User"
        return FakeUser(self, {})

    def get_all(self, doctype, filters, pluck):
        assert doctype == "User Social Login"
        rows = [
            {
                "parent": name,
                "parenttype": "User",
                "provider": row.provider,
                "userid": row.userid,
            }
            for name, record in self.records.items()
            for row in record["social_logins"]
        ]
        return [row[pluck] for row in rows if _matches(row, filters)]

    def generate_hash(self):
        return "generated-hash"

    def whitelist(self, allow_guest=False):
        def register(function):
            self.whitelisted[function.__name__] = allow_guest
            return function

        return register

    def logger(self, name):
        def record(message, *args):
            self.logged.append((name, message % args if args else message))

        return SimpleNamespace(info=record, warning=record)

    def throw(self, message, exc=FrappeValidationError):
        raise exc(message)

    def _info_via_oauth(self, provider, code, decoder=None):
        self.exchanges.append((provider, code, decoder))
        return copy.deepcopy(self.userinfo)

    def _login_oauth_user(self, data, *, provider=None, state):
        name = data["email"].lower()
        record = self.records.get(name)
        self.handovers.append(
            {
                "provider": provider,
                "state": state,
                "user": name,
                "committed": self.db.committed,
                "enabled": record["enabled"] if record else None,
            }
        )
        if not record or not record["enabled"]:
            return
        userid_claim = self.social_login_keys[provider]["user_id_property"] or "sub"
        if provider not in {row.provider for row in record["social_logins"]}:
            record["social_logins"].append(
                SimpleNamespace(provider=provider, userid=data[userid_claim])
            )

    def _upstream_custom(self, code, state):
        self.upstream_custom.append((code, state))

    def modules(self):
        """Return the ``sys.modules`` entries that make this object ``frappe``.

        Returns:
            Module name to module, for ``patch.dict(sys.modules, ...)``.
        """
        oauth2_logins = ModuleType("frappe.integrations.oauth2_logins")
        oauth2_logins.decoder_compat = json.loads
        oauth2_logins.custom = self._upstream_custom
        integrations = ModuleType("frappe.integrations")
        integrations.oauth2_logins = oauth2_logins
        oauth = ModuleType("frappe.utils.oauth")
        oauth.get_email = lambda data: (
            data.get("email") or data.get("upn") or data.get("unique_name")
        )
        oauth.get_info_via_oauth = self._info_via_oauth
        oauth.login_oauth_user = self._login_oauth_user
        utils = ModuleType("frappe.utils")
        utils.oauth = oauth
        return {
            "frappe": self,
            "frappe.integrations": integrations,
            "frappe.integrations.oauth2_logins": oauth2_logins,
            "frappe.utils": utils,
            "frappe.utils.oauth": oauth,
        }
