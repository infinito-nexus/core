from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest import mock

from infinito_elector_src.__main__ import parse_args

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src

COMMON = {
    "ELECTOR_ENGINE": "mariadb",
    "ELECTOR_HOST_ID": "m1",
    "ELECTOR_PEERS": "m1,m2",
    "ELECTOR_PEER_TEMPLATE": "mariadb-{host}",
    "ELECTOR_ETCD_ENDPOINTS": "https://etcd-m1:2379",
    "ELECTOR_ETCD_USER": "mariadb-elector",
    "ELECTOR_ETCD_PASSWORD_FILE": "/run/secrets/etcd",
    "ELECTOR_KEY": "/infinito/mariadb/writer",
    "ELECTOR_PORT": "8009",
}
MARIADB = {
    "ELECTOR_MARIADB_DEFAULTS_FILE": "/etc/elector.cnf",
    "ELECTOR_MARIADB_SOCKET": "/run/mysqld/mysqld.sock",
    "ELECTOR_MARIADB_LOCAL_USER": "mysql",
    "ELECTOR_REPLICATION_USER": "replication",
    "ELECTOR_REPLICATION_PASSWORD_FILE": "/run/secrets/repl",
}
OPENLDAP = {
    "ELECTOR_LDAP_DATABASE_DN": "olcDatabase={1}mdb,cn=config",
    "ELECTOR_LDAP_SUFFIX": "dc=example,dc=test",
    "ELECTOR_LDAP_BIND_DN": "cn=admin,dc=example,dc=test",
    "ELECTOR_LDAP_BIND_PASSWORD_FILE": "/run/slapd/pw",
}


def _parse(env):
    with mock.patch.dict(os.environ, env, clear=True):
        return parse_args([])


def _rejected(env) -> bool:
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            _parse(env)
    except SystemExit:
        return True
    return False


class TestParseArgs(unittest.TestCase):
    def test_mariadb_reads_every_option_from_env(self) -> None:
        args = _parse({**COMMON, **MARIADB})
        self.assertEqual(args.etcd_endpoints, "https://etcd-m1:2379")
        self.assertEqual(args.port, 8009)
        self.assertEqual(args.key, "/infinito/mariadb/writer")
        self.assertEqual(args.mariadb_socket, "/run/mysqld/mysqld.sock")

    def test_openldap_reads_every_option_from_env(self) -> None:
        args = _parse({**COMMON, **OPENLDAP, "ELECTOR_ENGINE": "openldap"})
        self.assertEqual(args.ldap_database_dn, "olcDatabase={1}mdb,cn=config")

    def test_every_deployment_setting_is_required(self) -> None:
        for name in (*COMMON, *MARIADB):
            with self.subTest(missing=name):
                env = {**COMMON, **MARIADB}
                del env[name]
                self.assertTrue(_rejected(env))

    def test_a_seed_port_needs_the_seed_relay(self) -> None:
        env = {**COMMON, **MARIADB, "ELECTOR_SEED_PORT": "4444"}
        self.assertTrue(_rejected(env))
        relay = "/opt/db-elector/seed_relay.py"
        args = _parse({**env, "ELECTOR_SEED_RELAY": relay})
        self.assertEqual(args.seed_relay, relay)

    def test_openldap_settings_are_required_for_openldap(self) -> None:
        for name in OPENLDAP:
            with self.subTest(missing=name):
                env = {**COMMON, **OPENLDAP, "ELECTOR_ENGINE": "openldap"}
                del env[name]
                self.assertTrue(_rejected(env))

    def test_no_lock_backend_choice(self) -> None:
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
            mock.patch.dict(os.environ, {**COMMON, **MARIADB}, clear=True),
        ):
            parse_args(["--lock", "kubernetes"])


if __name__ == "__main__":
    unittest.main()
