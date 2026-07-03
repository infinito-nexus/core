import unittest

from plugins.filter.ca_trust_paths import CA_CONTAINER_CERT, ca_cert_host
from utils import PROJECT_ROOT
from utils.cache.files import read_text

RUNTIME_SCRIPTS = (
    PROJECT_ROOT / "roles/sys-svc-compose-ca/files/compose_ca.py",
    PROJECT_ROOT / "roles/sys-svc-container/files/container.py",
)


class TestCaTrustPaths(unittest.TestCase):
    def test_host_path_derives_from_software_domain(self):
        self.assertEqual(
            ca_cert_host("infinito.nexus"), "/etc/infinito.nexus/ca/root-ca.crt"
        )
        self.assertEqual(ca_cert_host("example.org"), "/etc/example.org/ca/root-ca.crt")

    def test_container_path_is_stable(self):
        self.assertEqual(CA_CONTAINER_CERT, "/tmp/infinito/ca/root-ca.crt")

    def test_runtime_scripts_pin_the_container_spot(self):
        expected = f'"{CA_CONTAINER_CERT}"'
        for script in RUNTIME_SCRIPTS:
            self.assertIn(
                expected,
                read_text(str(script)),
                f"{script} no longer carries the SPOT container CA path; "
                "update plugins/filter/ca_trust_paths.py and the script together",
            )

    def test_env_handler_exports_the_host_spot(self):
        from utils.env.builder import BuildContext, EnvBuilder
        from utils.env.handlers import infinito_ca_cert_host as handler

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
