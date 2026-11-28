import unittest

from utils.roles.db.endpoint import (
    KEEPALIVE_SYSCTLS,
    DbEndpointError,
    endpoint_settings,
    endpoint_sysctls,
    render_haproxy_cfg,
    unprivileged_port_start,
)
from utils.roles.meta_lookup import get_role_ports


def _timings(fall):
    return (
        "resolvers docker resolve-prefer ipv4 init-addr none "
        f"inter 1s fastinter 500ms downinter 1s fall {fall} rise 1 "
        "on-marked-down shutdown-sessions"
    )


TIMINGS = _timings(3)


def _instances(engine):
    return [{"service": f"{engine}-{h}"} for h in ("mgr-01", "mgr-02", "mgr-03")]


def _ports(role):
    return get_role_ports(role, "internal")


class TestEndpointSettings(unittest.TestCase):
    def test_postgres_reads_its_ports_from_meta(self):
        ports = _ports("svc-db-postgres")
        self.assertEqual(
            endpoint_settings("svc-db-postgres", _ports("svc-db-postgres")),
            {
                "engine": "postgres",
                "port": ports["postgres"],
                "backend_port": ports["postgres"],
                "check": "http",
                "check_port": ports["patroni"],
                "check_path": "/primary",
                "check_timeout": 3,
                "check_fall": 5,
            },
        )

    def test_engines_without_a_declared_grace_keep_the_defaults(self):
        for role in ("svc-db-mariadb", "svc-db-openldap", "svc-db-redis"):
            settings = endpoint_settings(role, _ports(role))
            self.assertEqual(settings["check_timeout"], 1, role)
            self.assertEqual(settings["check_fall"], 3, role)

    def test_openldap_routes_to_the_instance_port(self):
        ports = _ports("svc-db-openldap")
        settings = endpoint_settings("svc-db-openldap", _ports("svc-db-openldap"))
        self.assertEqual(settings["port"], ports["ldap"])
        self.assertEqual(settings["backend_port"], ports["instance"])
        self.assertEqual(settings["check_port"], ports["writer"])

    def test_redis_check_has_no_http_fields(self):
        settings = endpoint_settings("svc-db-redis", _ports("svc-db-redis"))
        self.assertEqual(settings["check"], "redis")
        self.assertIsNone(settings["check_port"])
        self.assertIsNone(settings["check_path"])

    def test_engine_without_endpoint_raises(self):
        with self.assertRaises(DbEndpointError):
            endpoint_settings("svc-dcs-etcd", _ports("svc-dcs-etcd"))


class TestUnprivilegedPortStart(unittest.TestCase):
    def test_privileged_port_needs_sysctl(self):
        self.assertEqual(unprivileged_port_start(389), 389)

    def test_unprivileged_port_needs_none(self):
        self.assertIsNone(unprivileged_port_start(5432))


class TestKeepalive(unittest.TestCase):
    def test_probes_start_well_before_the_load_balancer_idle_drop(self):
        self.assertLess(KEEPALIVE_SYSCTLS["net.ipv4.tcp_keepalive_time"], 900)

    def test_every_endpoint_carries_the_keepalive_sysctls(self):
        self.assertEqual(endpoint_sysctls(5432), KEEPALIVE_SYSCTLS)
        self.assertEqual(
            endpoint_sysctls(389),
            {**KEEPALIVE_SYSCTLS, "net.ipv4.ip_unprivileged_port_start": 389},
        )

    def test_haproxy_sends_keepalives_on_both_legs(self):
        cfg = render_haproxy_cfg(
            endpoint_settings("svc-db-postgres", _ports("svc-db-postgres")),
            [{"service": "postgres-m1"}],
        )
        self.assertIn("    option clitcpka\n", cfg)
        self.assertIn("    option srvtcpka\n", cfg)


class TestPostgres(unittest.TestCase):
    def setUp(self):
        self.ports = _ports("svc-db-postgres")
        self.cfg = render_haproxy_cfg(
            endpoint_settings("svc-db-postgres", _ports("svc-db-postgres")),
            _instances("postgres"),
        )

    def test_server_lines(self):
        for host in ("mgr-01", "mgr-02", "mgr-03"):
            self.assertIn(
                f"    server postgres-{host} postgres-{host}:{self.ports['postgres']} "
                f"check port {self.ports['patroni']} {_timings(5)}\n",
                self.cfg,
            )

    def test_checks(self):
        self.assertIn("    option httpchk GET /primary\n", self.cfg)
        self.assertIn("    http-check expect status 200\n", self.cfg)
        self.assertIn("    timeout check 3s\n", self.cfg)
        self.assertIn(f"    bind :{self.ports['postgres']}\n", self.cfg)
        self.assertIn("    nameserver dns 127.0.0.11:53\n", self.cfg)

    def test_no_stats_listener(self):
        self.assertNotIn("stats enable", self.cfg)
        self.assertNotIn("stats uri", self.cfg)
        self.assertIn("stats socket /tmp/haproxy-admin.sock mode 600", self.cfg)


class TestElectorEngines(unittest.TestCase):
    def test_mariadb(self):
        ports = _ports("svc-db-mariadb")
        cfg = render_haproxy_cfg(
            endpoint_settings("svc-db-mariadb", _ports("svc-db-mariadb")),
            _instances("mariadb"),
        )
        self.assertIn("    option httpchk GET /writer\n", cfg)
        self.assertIn("    timeout check 1s\n", cfg)
        self.assertIn(f"    bind :{ports['mariadb']}\n", cfg)
        self.assertIn(
            f"    server mariadb-mgr-02 mariadb-mgr-02:{ports['mariadb']} "
            f"check port {ports['writer']} {TIMINGS}\n",
            cfg,
        )

    def test_openldap_routes_ldap_to_slapd_instance_port(self):
        ports = _ports("svc-db-openldap")
        cfg = render_haproxy_cfg(
            endpoint_settings("svc-db-openldap", _ports("svc-db-openldap")),
            _instances("openldap"),
        )
        self.assertIn("    option httpchk GET /writer\n", cfg)
        self.assertIn(f"    bind :{ports['ldap']}\n", cfg)
        self.assertIn(
            f"    server openldap-mgr-01 openldap-mgr-01:{ports['instance']} "
            f"check port {ports['writer']} {TIMINGS}\n",
            cfg,
        )

    def test_http_check_needs_port_and_path(self):
        settings = {
            **endpoint_settings("svc-db-mariadb", _ports("svc-db-mariadb")),
            "check_port": None,
        }
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(settings, _instances("mariadb"))


class TestRedis(unittest.TestCase):
    def setUp(self):
        self.settings = endpoint_settings("svc-db-redis", _ports("svc-db-redis"))
        self.cfg = render_haproxy_cfg(
            self.settings,
            _instances("redis"),
            check_user="haproxy-check",
            check_password="Secret123",
        )

    def test_server_line_has_no_check_port(self):
        self.assertIn(
            f"    server redis-mgr-03 redis-mgr-03:{self.settings['port']} check {TIMINGS}\n",
            self.cfg,
        )

    def test_tcp_check_sequence(self):
        expected = (
            "    option tcp-check\n"
            "    tcp-check connect\n"
            "    tcp-check send AUTH\\ haproxy-check\\ Secret123\\r\\n\n"
            "    tcp-check expect string +OK\n"
            "    tcp-check send info\\ replication\\r\\n\n"
            "    tcp-check expect string role:master\n"
            "    tcp-check expect rstring connected_slaves:[1-9]\n"
        )
        self.assertIn(expected, self.cfg)
        self.assertNotIn("httpchk", self.cfg)

    def test_user_and_password_required_and_safe(self):
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(self.settings, _instances("redis"), check_password="x")
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(self.settings, _instances("redis"), check_user="u")
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(
                self.settings, _instances("redis"), check_user="u", check_password="a b"
            )


class TestErrors(unittest.TestCase):
    def test_unknown_check(self):
        settings = {
            **endpoint_settings("svc-db-redis", _ports("svc-db-redis")),
            "check": "tcp",
        }
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(settings, _instances("redis"))

    def test_no_instances(self):
        with self.assertRaises(DbEndpointError):
            render_haproxy_cfg(
                endpoint_settings("svc-db-postgres", _ports("svc-db-postgres")), []
            )


if __name__ == "__main__":
    unittest.main()
