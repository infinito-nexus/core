import hashlib
import unittest

from utils.roles.openldap_ha import (
    SERVER_ID_MAX,
    OpenLDAPHAError,
    batch_result_codes,
    forbidden_bind_writes,
    render_cn_config,
    schema_drops,
    server_id,
    server_ids,
)

SCHEMAS = [
    {
        "name": "nextcloud",
        "attribute_types": ["( 1.3.6.1.4.1.99999.1 NAME 'nextcloudQuota' )"],
        "object_classes": [
            "( 1.3.6.1.4.1.99999.2 NAME 'nextcloudUser' AUXILIARY MAY ( nextcloudQuota ) )"
        ],
    },
    {
        "name": "openssh-lpk",
        "attribute_types": [
            "( 1.3.6.1.4.1.24552.1.1 NAME 'sshPublicKey' )",
            "( 1.3.6.1.4.1.24552.1.2 NAME 'sshFingerprint' )",
        ],
        "object_classes": [],
    },
]


def _render(**overrides):
    kwargs = {
        "host_id": "mgr-01",
        "host_ids": ["mgr-01", "mgr-02", "mgr-03"],
        "peer_template": "ldap://openldap-{host}:1389",
        "suffix": "dc=infinito,dc=example",
        "root_dn": "cn=administrator,dc=infinito,dc=example",
        "schemas": SCHEMAS,
    }
    kwargs.update(overrides)
    return render_cn_config(**kwargs)


def _entries(ldif):
    return [block for block in ldif.strip().split("\n\n") if block.strip()]


def _dns(ldif):
    return [block.splitlines()[0] for block in _entries(ldif)]


class TestServerId(unittest.TestCase):
    def test_is_deterministic_hash_into_range(self):
        expected = int(hashlib.sha256(b"mgr-01").hexdigest(), 16) % SERVER_ID_MAX + 1
        self.assertEqual(server_id("mgr-01"), expected)
        self.assertEqual(server_id("mgr-01"), server_id("mgr-01"))

    def test_stays_in_openldap_range(self):
        for index in range(500):
            value = server_id(f"host-{index}")
            self.assertGreaterEqual(value, 1)
            self.assertLessEqual(value, 4095)

    def test_rejects_empty_host_id(self):
        with self.assertRaises(OpenLDAPHAError):
            server_id("")


class TestServerIds(unittest.TestCase):
    def test_maps_every_host(self):
        ids = server_ids(["mgr-01", "mgr-02", "mgr-03"])
        self.assertEqual(set(ids), {"mgr-01", "mgr-02", "mgr-03"})
        self.assertEqual(ids["mgr-02"], server_id("mgr-02"))

    def test_collision_fails_naming_both_hosts(self):
        colliding = None
        seen = {}
        for index in range(20000):
            host = f"h{index}"
            value = server_id(host)
            if value in seen:
                colliding = (seen[value], host)
                break
            seen[value] = host
        self.assertIsNotNone(colliding)
        with self.assertRaises(OpenLDAPHAError) as ctx:
            server_ids(list(colliding))
        self.assertIn(colliding[0], str(ctx.exception))
        self.assertIn(colliding[1], str(ctx.exception))

    def test_duplicate_host_fails(self):
        with self.assertRaises(OpenLDAPHAError):
            server_ids(["mgr-01", "mgr-01"])


class TestRenderCnConfig(unittest.TestCase):
    def test_server_id_is_own_hash(self):
        self.assertIn(f"olcServerID: {server_id('mgr-01')}\n", _render())

    def test_entry_order_parents_first(self):
        dns = _dns(_render())
        self.assertEqual(dns[0], "dn: cn=config")
        self.assertLess(
            dns.index("dn: cn=schema,cn=config"),
            dns.index("dn: cn=nextcloud,cn=schema,cn=config"),
        )
        mdb = "dn: olcDatabase={1}mdb,cn=config"
        self.assertLess(
            dns.index(mdb),
            dns.index("dn: olcOverlay={0}syncprov,olcDatabase={1}mdb,cn=config"),
        )

    def test_includes_core_schemas_before_custom(self):
        ldif = _render()
        core = ldif.index("include: file:///etc/ldap/schema/core.ldif")
        nis = ldif.index("include: file:///etc/ldap/schema/nis.ldif")
        self.assertLess(core, nis)
        self.assertLess(nis, ldif.index("cn: nextcloud"))

    def test_custom_schemas_static(self):
        ldif = _render()
        self.assertIn(
            "olcAttributeTypes: ( 1.3.6.1.4.1.24552.1.2 NAME 'sshFingerprint' )", ldif
        )
        self.assertIn("cn: openssh-lpk", ldif)

    def test_data_database_read_only_multi_provider(self):
        ldif = _render()
        self.assertIn("olcReadOnly: TRUE", ldif)
        self.assertIn("olcMultiProvider: TRUE", ldif)

    def test_syncrepl_to_every_peer_not_self(self):
        ldif = _render()
        self.assertIn("provider=ldap://openldap-mgr-02:1389", ldif)
        self.assertIn("provider=ldap://openldap-mgr-03:1389", ldif)
        self.assertNotIn("provider=ldap://openldap-mgr-01:1389", ldif)
        self.assertEqual(ldif.count("olcSyncrepl:"), 2)

    def test_syncrepl_excludes_memberof(self):
        for line in _render().splitlines():
            if line.startswith("olcSyncrepl:"):
                self.assertIn("exattrs=memberOf", line)

    def test_rids_unique_and_stable_across_instances(self):
        first = _render(host_id="mgr-01")
        second = _render(host_id="mgr-02")
        self.assertIn("rid=002 provider=ldap://openldap-mgr-02:1389", first)
        self.assertIn("rid=001 provider=ldap://openldap-mgr-01:1389", second)

    def test_memberof_addcheck_and_refint(self):
        ldif = _render()
        self.assertIn("olcMemberOfAddCheck: TRUE", ldif)
        self.assertIn("olcOverlay: {2}refint", ldif)
        self.assertIn("olcModuleLoad: {3}syncprov", ldif)

    def test_secrets_are_placeholders(self):
        ldif = _render()
        self.assertIn("olcRootPW: @ROOT_PW_HASH@", ldif)
        self.assertIn("credentials=@ROOT_PW@", ldif)

    def test_no_ppolicy_or_lastbind(self):
        self.assertEqual(forbidden_bind_writes(_render()), [])

    def test_host_must_be_in_group(self):
        with self.assertRaises(OpenLDAPHAError):
            _render(host_id="mgr-09")

    def test_deterministic(self):
        self.assertEqual(_render(), _render())


class TestBatchResultCodes(unittest.TestCase):
    def test_every_refused_entry_is_reported(self):
        stderr = (
            "ldap_add: Already exists (68)\n"
            "ldap_modify: Object class violation (65)\n"
            "\tadditional info: object class 'ldapPublicKey' requires attribute 'sshPublicKey'\n"
            "ldap_modify: Type or value exists (20)\n"
        )
        self.assertEqual(batch_result_codes(stderr), [68, 65, 20])

    def test_a_clean_batch_has_no_codes(self):
        self.assertEqual(batch_result_codes(""), [])
        self.assertEqual(batch_result_codes(None), [])


class TestForbiddenBindWrites(unittest.TestCase):
    def test_detects_ppolicy_and_lastbind(self):
        live = (
            "dn: olcOverlay={3}ppolicy,olcDatabase={1}mdb,cn=config\n"
            "olcOverlay: {3}ppolicy\n\n"
            "dn: olcDatabase={1}mdb,cn=config\n"
            "olcLastBind: TRUE\n"
        )
        self.assertEqual(forbidden_bind_writes(live), ["ppolicy", "olcLastBind"])

    def test_lastbind_false_is_fine(self):
        self.assertEqual(forbidden_bind_writes("olcLastBind: FALSE\n"), [])


class TestSchemaDrops(unittest.TestCase):
    def test_reports_live_schema_missing_from_render(self):
        live = [
            "cn={0}core,cn=schema,cn=config",
            "cn={4}nextcloud,cn=schema,cn=config",
            "cn={7}custom,cn=schema,cn=config",
        ]
        self.assertEqual(schema_drops(live, _render()), ["custom"])

    def test_nothing_dropped(self):
        live = [
            "cn={4}nextcloud,cn=schema,cn=config",
            "cn={1}cosine,cn=schema,cn=config",
        ]
        self.assertEqual(schema_drops(live, _render()), [])


if __name__ == "__main__":
    unittest.main()
