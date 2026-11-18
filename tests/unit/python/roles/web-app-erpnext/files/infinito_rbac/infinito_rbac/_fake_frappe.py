"""In-memory stand-in for the slice of Frappe the ``infinito_rbac`` app calls.

``login_oauth_user`` behaves like Frappe 16's: it takes the account named after
the sign-in's e-mail address, refuses a missing one because the Social Login Key
denies sign-ups, refuses a disabled one, and links an enabled one to the
signing-in user when it has no ``keycloak`` row yet.
"""

from __future__ import annotations

import copy
import json
import re
from types import ModuleType, SimpleNamespace

from ldap3.utils import conv as ldap_conv

from ._app import app_modules

LDAP_SETTINGS_MODULE = "frappe.integrations.doctype.ldap_settings.ldap_settings"
GRANT_PARENT = "infinito_rbac_mapped_role"
ID_PARENT = "infinito_rbac_directory_id"
DIRECTORY_URL = "ldap://openldap:389"


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

    def append(self, table, row):
        self._values[table].append(SimpleNamespace(**row))

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

    def save(self, ignore_permissions=False):
        self._frappe.saves.append(
            (
                self._values["name"],
                ignore_permissions or getattr(self.flags, "ignore_permissions", False),
            )
        )
        self._frappe.records[self._values["name"]] = copy.deepcopy(self._values)
        return self


class FakeRole:
    def __init__(self, frappe, role_name):
        self._frappe = frappe
        self.flags = SimpleNamespace(ignore_permissions=False)
        self.role_name = role_name

    def insert(self):
        assert self.flags.ignore_permissions
        assert self.role_name not in self._frappe.site_roles
        self._frappe.site_roles.add(self.role_name)
        return self


def _values(entry, name):
    value = entry.get(name)
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _matching(value):
    """Args:
        value: an attribute value or a filter's assertion value.

    Returns:
        The value as the directory's case-ignore matching rules compare it.
    """
    return " ".join(value.split()).lower()


def _unescaped(value):
    """Args:
        value: a filter's assertion value, escaped as RFC 4515 ``\\XX``.

    Returns:
        The value the assertion compares.
    """
    return re.sub(
        r"\\([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), value
    )


class FakeConnection:
    def __init__(self, frappe):
        self._frappe = frappe
        self.entries = []

    def search(self, search_base, search_filter, attributes):
        self._frappe.ldap_searches.append((search_base, search_filter, attributes))
        if self._frappe.outage == "search":
            raise OSError(f"socket receive error from {DIRECTORY_URL}")
        assert search_filter.startswith("(|")
        terms = re.findall(r"\(([^()|=]+)=([^()]*)\)", search_filter)
        self.entries = [
            SimpleNamespace(
                entry_attributes_as_dict={
                    name: _values(entry, name) for name in attributes if name in entry
                }
            )
            for entry in self._frappe.entries()
            if any(
                _matching(_unescaped(value)) in map(_matching, _values(entry, name))
                for name, value in terms
            )
        ]
        return bool(self.entries)

    def unbind(self):
        self._frappe.unbinds += 1
        if self._frappe.unbind_fails:
            raise OSError(f"socket send error to {DIRECTORY_URL}")


class FakeLDAPSettings:
    _frappe = None
    base_dn = "cn=administrator,dc=infinito,dc=example"
    ldap_search_path_user = "ou=users,dc=infinito,dc=example"
    ldap_username_field = "uid"
    ldap_email_field = "mail"

    @property
    def ldap_server_url(self):
        return "" if self._frappe.directory is None else DIRECTORY_URL

    def get_password(self, raise_exception=True):
        return "bind-password"

    def connect_to_ldap(self, base_dn, password, read_only=True):
        """Args:
            base_dn: the bind DN.
            password: the bind password.
            read_only: whether the connection only reads.

        Returns:
            A connection to the fake directory.

        Raises:
            FrappeValidationError: no directory or a connect outage, its message
                appended to ``message_log``.
        """
        assert (base_dn, password) == (self.base_dn, "bind-password")
        if self._frappe.directory is None or self._frappe.outage == "connect":
            message = f"socket connection error while opening {DIRECTORY_URL}"
            self._frappe.message_log.append(message)
            raise FrappeValidationError(message)
        return FakeConnection(self._frappe)

    @staticmethod
    def update_user_fields(user, user_data):
        for key, value in user_data.items():
            if key != "email":
                setattr(user, key, value)
        user.save(ignore_permissions=True)

    def create_or_update_user(self, user_data, groups=None):
        raise AssertionError("the subclass replaces the upstream account handling")


class FakeDb:
    def __init__(self, frappe):
        self._frappe = frappe
        self.committed = False

    def exists(self, doctype, name):
        self._frappe.lookups.append((doctype, name))
        if doctype == "Role":
            return name in self._frappe.site_roles
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
        self.site_roles = {
            "System Manager",
            "Sales User",
            "Purchase User",
            "Stock User",
            "Accounts User",
            "Customer",
        }
        self.saves = []
        self.default_rows = []
        self.session = SimpleNamespace(user="Guest")
        self.social_login_keys = {
            "keycloak": {"user_id_property": "preferred_username"}
        }
        self.conf = {}
        self.directory = None
        self.extra_entries = []
        self.outage = None
        self.unbinds = 0
        self.unbind_fails = False
        self.message_log = []
        self.ldap_searches = []
        self.LDAPSettings = type("LDAPSettings", (FakeLDAPSettings,), {"_frappe": self})
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
        """Args:
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

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            assert doctype["doctype"] == "Role"
            return FakeRole(self, doctype["role_name"])
        self.lookups.append((doctype, name))
        assert doctype == "User"
        return FakeUser(self, copy.deepcopy(self.records[name]))

    def new_doc(self, doctype):
        assert doctype == "User"
        return FakeUser(self, {})

    def get_single(self, doctype):
        assert doctype == "LDAP Settings"
        return self.LDAPSettings()

    def entries(self):
        """Returns:
        ``{uid, mail, entryUUID}`` of one entry per ``directory`` username at
        its default address, then ``extra_entries``.
        """
        return [
            {"uid": username, "mail": f"{username}@infinito.example", "entryUUID": uuid}
            for username, uuid in (self.directory or {}).items()
        ] + list(self.extra_entries)

    def grants(self, name):
        return {
            row["defvalue"]
            for row in self.default_rows
            if row["parent"] == GRANT_PARENT and row["defkey"] == name
        }

    def record(self, name, role):
        self.default_rows.append(
            {"parent": GRANT_PARENT, "defkey": name, "defvalue": role}
        )

    def ids(self, name):
        return {
            row["defvalue"]
            for row in self.default_rows
            if row["parent"] == ID_PARENT and row["defkey"] == name
        }

    def record_id(self, name, uuid):
        self.default_rows.append(
            {"parent": ID_PARENT, "defkey": name, "defvalue": uuid}
        )

    def get_all(self, doctype, filters, pluck):
        if doctype == "DefaultValue":
            return [row[pluck] for row in self.default_rows if _matches(row, filters)]
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

        return SimpleNamespace(info=record, warning=record, error=record)

    def throw(self, message, exc=FrappeValidationError):
        raise exc(message)

    def clear_messages(self):
        self.message_log.clear()

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
        """Returns:
        Module name to module of the ``sys.modules`` entries that make this
        object ``frappe``, for ``patch.dict(sys.modules, ...)``.
        """
        oauth2_logins = ModuleType("frappe.integrations.oauth2_logins")
        oauth2_logins.decoder_compat = json.loads
        oauth2_logins.custom = self._upstream_custom
        ldap_settings = ModuleType(LDAP_SETTINGS_MODULE)
        ldap_settings.LDAPSettings = self.LDAPSettings
        ldap_package = ModuleType(LDAP_SETTINGS_MODULE.rpartition(".")[0])
        ldap_package.ldap_settings = ldap_settings
        doctype = ModuleType("frappe.integrations.doctype")
        doctype.ldap_settings = ldap_package
        integrations = ModuleType("frappe.integrations")
        integrations.oauth2_logins = oauth2_logins
        integrations.doctype = doctype
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
            "frappe.integrations.doctype": doctype,
            ldap_package.__name__: ldap_package,
            LDAP_SETTINGS_MODULE: ldap_settings,
            "frappe.utils": utils,
            "frappe.utils.oauth": oauth,
            ldap_conv.__name__: ldap_conv,
            **app_modules(self),
        }
