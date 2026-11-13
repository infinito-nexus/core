import unittest

from ansible.errors import AnsibleError

from utils.tls.overrides import with_rendered_tls


class TestWithRenderedTls(unittest.TestCase):
    def test_with_rendered_tls_renders_every_override_into_a_copy(self):
        app = {
            "server": {
                "tls": {
                    "enabled": "{{ A }}",
                    "mode": "{{ B }}",
                    "flavor": "{{ C }}",
                    "domains_san": ["san.example"],
                }
            }
        }
        rendered = with_rendered_tls(
            app, lambda value: value.strip("{} "), where="tls: 'web-app-a'"
        )
        self.assertEqual(
            rendered["server"]["tls"],
            {
                "enabled": "A",
                "mode": "B",
                "flavor": "C",
                "domains_san": ["san.example"],
            },
        )
        self.assertEqual(app["server"]["tls"]["enabled"], "{{ A }}")

    def test_with_rendered_tls_keeps_an_app_without_tls_overrides(self):
        for app in ({}, {"server": {}}, {"server": {"tls": None}}):
            with self.subTest(app=app):
                self.assertIs(with_rendered_tls(app, None, where="t"), app)

    def test_with_rendered_tls_fails_on_an_override_that_stays_template_text(self):
        for key in ("enabled", "mode", "flavor"):
            with self.subTest(key=key):
                with self.assertRaises(AnsibleError) as ctx:
                    with_rendered_tls(
                        {"server": {"tls": {key: "{{ X }}"}}},
                        None,
                        where="tls: 'web-app-a'",
                    )
                self.assertIn(f"tls: 'web-app-a' server.tls.{key}", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
