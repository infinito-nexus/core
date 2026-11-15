"""The served_domains lookup resolves member hosts without ever failing a play."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.served_domains import LookupModule

APP = "web-app-wordpress"
APPLICATIONS = {
    APP: {
        "domains": {
            "canonical": ["blog.main.test"],
            "served": [{"parent": "user.blog.main.test", "role": "site-owner"}],
        },
    },
    "web-app-plain": {},
}
USERS = {
    "biber": {"username": "biber", "roles": ["site-owner"]},
    "dotted": {"username": "harry.beaver", "roles": ["site-owner"]},
}
SELF_SIGNED = {"TLS_ENABLED": True, "TLS_MODE": "self_signed"}
WEBROOT = {
    "TLS_ENABLED": True,
    "TLS_MODE": "letsencrypt",
    "CERTBOT_FLAVOR": "dedicated",
    "CERTBOT_ACME_CHALLENGE_METHOD": "webroot",
}


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def run(self, terms, variables=None, **kwargs):
        return [self.payload]


class TestServedDomainsLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()
        self.lookup._templar = None
        self.lookup._loader = None

    def _run(self, variables, application_ids, domains=None, applications=None):
        payloads = {
            "applications": applications or APPLICATIONS,
            "domains": domains or {APP: ["blog.main.test"]},
            "users": USERS,
        }
        with mock.patch(
            "plugins.lookup.served_domains.lookup_loader.get",
            side_effect=lambda name, **kwargs: _Stub(payloads[name]),
        ):
            return self.lookup.run(
                [], variables=variables, application_ids=application_ids
            )[0]

    def test_a_self_signed_host_serves_the_wildcard(self):
        result = self._run(SELF_SIGNED, [APP])
        self.assertEqual(
            ["*.user.blog.main.test"], [entry["name"] for entry in result["entries"]]
        )

    def test_a_webroot_host_serves_every_member_host(self):
        result = self._run(WEBROOT, [APP])
        self.assertEqual(
            ["biber.user.blog.main.test"],
            [entry["name"] for entry in result["entries"]],
        )

    def test_an_invalid_member_is_a_problem_of_the_role_not_of_the_play(self):
        problems = self._run(WEBROOT, [APP])["problems"]
        self.assertEqual(1, len(problems))
        self.assertIn("harry.beaver", problems[0])

    def test_a_member_host_that_repeats_a_redirect_source_is_a_problem(self):
        source = {"source": "biber.user.blog.main.test", "target": "blog.main.test"}
        variables = dict(WEBROOT, CURRENT_PLAY_REDIRECT_DOMAINS=[source])
        result = self._run(variables, [APP])
        self.assertEqual([], result["entries"])
        self.assertTrue(
            [problem for problem in result["problems"] if "repeats" in problem]
        )

    def test_a_play_without_a_declaring_application_serves_nothing(self):
        self.assertEqual(
            {"entries": [], "problems": []}, self._run({}, ["web-app-plain"])
        )

    def _templated(self, tls, **scope):
        applications = {
            **APPLICATIONS,
            APP: {**APPLICATIONS[APP], "server": {"tls": tls}},
        }
        return self._run(dict(WEBROOT, **scope), [APP], applications=applications)

    def test_a_templated_tls_override_decides_the_wildcard(self):
        self.lookup._templar = Templar(loader=DataLoader())
        for tls, scope in (
            ({"enabled": "{{ T_TLS }}"}, {"T_TLS": False}),
            ({"mode": "{{ T_MODE }}"}, {"T_MODE": "self_signed"}),
        ):
            with self.subTest(tls=tls):
                entries = self._templated(tls, **scope)["entries"]
                self.assertEqual(
                    ["*.user.blog.main.test"], [entry["name"] for entry in entries]
                )

    def test_a_tls_override_that_stays_template_text_raises(self):
        with self.assertRaises(AnsibleError):
            self._templated({"enabled": "{{ T_TLS }}"})

    def test_terms_or_a_missing_id_list_fail(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables=SELF_SIGNED, application_ids=[APP])
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables=SELF_SIGNED)


if __name__ == "__main__":
    unittest.main()
