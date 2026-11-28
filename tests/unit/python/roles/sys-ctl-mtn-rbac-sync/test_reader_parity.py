from __future__ import annotations

import base64
import sys
import types
import unittest

from ansible_collections.community.general.plugins.modules.ldap_search import (
    _extract_entry,
)

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

READER = PROJECT_ROOT / "roles/sys-ctl-mtn-rbac-sync/files/python/member_reader.py"
FILTER = PROJECT_ROOT / "plugins/filter/rbac/members.py"
DEPLOYED_MODULES = {
    "ldap_client": PROJECT_ROOT / "roles/svc-db-openldap/files/python/ldap/client.py",
}
READERS = {
    "tasks/utils/rbac/members.yml": "rbac_members_attributes",
    "tasks/utils/rbac/users.yml": "rbac_users_attributes",
}
LDAP = {
    "users_dn": "ou=users,dc=example,dc=org",
    "roles_dn": "ou=roles,dc=example,dc=org",
    "attributes": {
        "id": "uid",
        "mail": "mail",
        "name": "cn",
        "member_of": "memberOf",
        "uuid": "entryUUID",
    },
}
PHOTO = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x80, 0xC3])
ENTRY = {
    "uid": [b"carol"],
    "mail": [b"carol@example.org"],
    "cn": ["Carol Weiß".encode()],
    "entryUUID": [b"c4r0l"],
    "street": ["Hauptstraße 1".encode()],
    "jpegPhoto": [PHOTO, b"\x00second"],
}
EXTRA = ["street", "jpegPhoto", "l"]


def _module(name, path):
    module = types.ModuleType(name)
    exec(compile(read_text(str(path)), str(path), "exec"), module.__dict__)
    return module


def _reader():
    for name, path in DEPLOYED_MODULES.items():
        if name not in sys.modules:
            sys.modules[name] = _module(name, path)
    return _module("member_reader", READER)


def _search_result_entry(client, dn, attributes):
    """Return the SearchResultEntry content octets slapd sends for one entry.

    Args:
        client: the loaded ``ldap_client`` module.
        dn: the entry's DN.
        attributes: ``{name: [value octets]}``.
    """
    encoded = b"".join(
        client.tlv(
            client.SEQUENCE,
            client.tlv(client.OCTET_STRING, name.encode())
            + client.tlv(
                client.SET,
                b"".join(client.tlv(client.OCTET_STRING, value) for value in values),
            ),
        )
        for name, values in attributes.items()
    )
    return client.tlv(client.OCTET_STRING, dn.encode()) + client.tlv(
        client.SEQUENCE, encoded
    )


class _Directory:
    def __init__(self, entries):
        self.entries = entries

    def search(self, base, scope, search_filter, attributes):
        return self.entries


class TestTheDeployAndTheTimerHandOverOneMemberShape(unittest.TestCase):
    def test_text_and_binary_attributes_arrive_identically(self):
        reader = _reader()
        client = sys.modules["ldap_client"]
        dn = "uid=carol,ou=users,dc=example,dc=org"
        deploy = _module("rbac_members_filter", FILTER).rbac_ldap_members(
            [_extract_entry(dn, ENTRY, set(EXTRA))],
            "uid",
            "mail",
            "cn",
            "entryUUID",
            EXTRA,
        )
        timer = reader.directory_members(
            _Directory([client.parse_entry(_search_result_entry(client, dn, ENTRY))]),
            LDAP,
            "web-app-nextcloud",
            "@users",
            EXTRA,
        )

        self.assertEqual(deploy, timer)
        self.assertEqual(base64.b64decode(timer[0]["attributes"]["jpegPhoto"]), PHOTO)
        self.assertEqual(
            base64.b64decode(timer[0]["attributes"]["street"]).decode(),
            "Hauptstraße 1",
        )
        self.assertEqual(timer[0]["attributes"]["l"], "")
        self.assertEqual(timer[0]["name"], "Carol Weiß")

    def test_both_deploy_searches_request_and_encode_the_declared_attributes(self):
        for rel, parameter in READERS.items():
            searches = [
                task["community.general.ldap_search"]
                for task in load_yaml_any(str(PROJECT_ROOT / rel))
                if "community.general.ldap_search" in task
            ]
            with self.subTest(file=rel):
                self.assertEqual(len(searches), 2)
                for search in searches:
                    self.assertTrue(search["attrs"].endswith(f"+ {parameter} }}}}"))
                    self.assertEqual(
                        search["base64_attributes"], f"{{{{ {parameter} }}}}"
                    )


if __name__ == "__main__":
    unittest.main()
