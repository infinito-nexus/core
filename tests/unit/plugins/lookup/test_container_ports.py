import unittest
from typing import ClassVar
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule


def _apps():
    return {
        "web-app-gitea": {
            "services": {
                "gitea": {
                    "ports": {
                        "local": {"http": 8002},
                        "public": {"ssh": 2201},
                        "internal": {"http": 3000, "ssh": 22},
                    }
                }
            }
        }
    }


def _run(terms, *, app_id="web-app-gitea", **kwargs):
    with patch(
        "plugins.lookup.container_ports.get_merged_applications",
        return_value=_apps(),
    ):
        return LookupModule().run(terms, variables={"application_id": app_id}, **kwargs)


class TestContainerPortsLookup(unittest.TestCase):
    def test_local_scope_with_ip(self):
        self.assertEqual(
            _run([["gitea", "http", "10.0.0.1"]]),
            ['ports:\n  - "10.0.0.1:8002:3000"'],
        )

    def test_public_scope_without_ip(self):
        self.assertEqual(
            _run([["gitea", "ssh"]]),
            ['ports:\n  - "2201:22"'],
        )

    def test_local_scope_without_ip_drops_ip(self):
        self.assertEqual(
            _run([["gitea", "http"]]),
            ['ports:\n  - "8002:3000"'],
        )

    def test_multiple_mixed_terms(self):
        self.assertEqual(
            _run([["gitea", "http", "10.0.0.1"], ["gitea", "ssh"]]),
            ['ports:\n  - "10.0.0.1:8002:3000"\n  - "2201:22"'],
        )

    def test_application_id_kwarg_overrides_vars(self):
        self.assertEqual(
            _run(
                [["gitea", "http", "127.0.0.1"]],
                app_id="nope",
                application_id="web-app-gitea",
            ),
            ['ports:\n  - "127.0.0.1:8002:3000"'],
        )

    def test_ip_kwarg_is_removed(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea", "http"]], ip="10.0.0.1")

    def test_no_terms_raises(self):
        with self.assertRaises(AnsibleError):
            _run([])

    def test_bad_term_raises(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea"]])
        with self.assertRaises(AnsibleError):
            _run([["gitea", "http", "10.0.0.1", "extra"]])

    def test_unknown_protocol_raises(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea", "nope", "127.0.0.1"]])

    def test_missing_application_id_raises(self):
        with (
            patch(
                "plugins.lookup.container_ports.get_merged_applications",
                return_value=_apps(),
            ),
            self.assertRaises(AnsibleError),
        ):
            LookupModule().run([["gitea", "http"]], variables={})

    def test_application_id_unrendered_var_is_templated(self):
        class _Templar:
            available_variables: ClassVar[dict] = {}

            def template(self, value):
                return "web-app-gitea" if value == "{{ app }}" else value

        lookup = LookupModule()
        lookup._templar = _Templar()
        with patch(
            "plugins.lookup.container_ports.get_merged_applications",
            return_value=_apps(),
        ):
            out = lookup.run(
                [["gitea", "http", "10.0.0.1"]],
                variables={"application_id": "{{ app }}"},
            )
        self.assertEqual(out, ['ports:\n  - "10.0.0.1:8002:3000"'])


if __name__ == "__main__":
    unittest.main()
