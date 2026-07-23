import unittest

from plugins.filter.ca_trust_paths import ca_cert_host
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml

RUNTIME_SCRIPTS = (
    PROJECT_ROOT / "roles/sys-svc-compose-ca/files/compose_ca.py",
    PROJECT_ROOT / "roles/sys-svc-container/files/container.py",
)

_CA_TRUST = load_yaml(str(PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"))[
    "CA_TRUST"
]


class TestCaTrustPaths(unittest.TestCase):
    def test_host_path_derives_from_software_domain(self):
        self.assertEqual(
            ca_cert_host("infinito.nexus"), "/etc/infinito.nexus/ca/root-ca.crt"
        )
        self.assertEqual(ca_cert_host("example.org"), "/etc/example.org/ca/root-ca.crt")

    def test_group_vars_spot_holds_plain_container_paths(self):
        for key in ("inject_cert_container", "inject_wrapper_container"):
            value = _CA_TRUST[key]
            self.assertIsInstance(value, str)
            self.assertTrue(value.startswith("/"), f"{key} must be an absolute path")
            self.assertNotIn("{{", value, f"{key} must be a plain string")

    def test_runtime_scripts_carry_no_container_path_literal(self):
        for script in RUNTIME_SCRIPTS:
            content = read_text(str(script))
            for key in ("inject_cert_container", "inject_wrapper_container"):
                self.assertNotIn(
                    _CA_TRUST[key],
                    content,
                    f"{script} hardcodes {_CA_TRUST[key]}; it must take the value "
                    "from env/CLI so group_vars stays the only SPOT",
                )

    def test_env_handler_exports_the_host_spot(self):
        from utils.env.builder import BuildContext, EnvBuilder
        from utils.env.handlers.infinito import ca_cert_host as handler

        eb = EnvBuilder()
        handler.apply(
            eb,
            BuildContext(
                static={},
                static_comments={},
                repo_root=PROJECT_ROOT,
                on_gha=False,
                on_act=False,
            ),
        )
        self.assertEqual(
            eb.values["INFINITO_CA_CERT_HOST"], ca_cert_host("infinito.nexus")
        )


if __name__ == "__main__":
    unittest.main()
