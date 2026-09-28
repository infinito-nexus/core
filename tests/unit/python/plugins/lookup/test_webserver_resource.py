import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.webserver_resource import PROXY_ROLE, LookupModule

RESOURCE = {"cpus": "0.5", "pids_limit": 512, "host_cpus": 20}


class _Templar:
    def __init__(self, resolved):
        self._resolved = resolved

    def template(self, value):
        return self._resolved.get(value, value)


def _run(
    key,
    proxy,
    app,
    application_id="web-app-docs",
    service_name="",
    declared_as=None,
    templar=None,
):
    applications = {
        PROXY_ROLE: {"services": {"openresty": {key: proxy}}},
        application_id: {"services": {"docs": {key: app}}},
    }
    variables = {
        "application_id": declared_as or application_id,
        "service_name": service_name,
    }
    with (
        patch("plugins.lookup.webserver_resource.ApplicationsLookup") as apps,
        patch("plugins.lookup.webserver_resource.ResourceLookup") as resource,
    ):
        apps.return_value.run.return_value = [applications]
        resource.return_value.run.side_effect = lambda terms, **_k: [RESOURCE[terms[0]]]
        lookup = LookupModule()
        if templar is not None:
            lookup._templar = templar
        return lookup.run([key], variables=variables)


class TestWebserverResource(unittest.TestCase):
    def test_the_tighter_of_the_two_wins(self):
        self.assertEqual(_run("cpus", proxy="4", app="2"), [2.0])
        self.assertEqual(_run("cpus", proxy="1", app="2"), [1.0])

    def test_a_percentage_is_resolved_before_the_comparison(self):
        """95% of 20 is 19, so a literal 4 is the tighter of the pair."""
        self.assertEqual(_run("cpus", proxy="4", app="95%"), [4.0])

    def test_a_percentage_can_be_the_tighter_one(self):
        self.assertEqual(_run("cpus", proxy="50%", app="16"), [10.0])

    def test_pids_limit_stays_an_integer(self):
        result = _run("pids_limit", proxy=1024, app=512)
        self.assertEqual(result, [512])
        self.assertIsInstance(result[0], int)

    def test_an_application_id_that_is_still_a_template_is_resolved(self):
        """sys-stk-full sets application_id from a variable, so the play holds
        the unrendered string and the lookup must template it itself."""
        result = _run(
            "cpus",
            proxy="4",
            app="2",
            declared_as="{{ sys_stk_full_application_id }}",
            templar=_Templar({"{{ sys_stk_full_application_id }}": "web-app-docs"}),
        )
        self.assertEqual(result, [2.0])

    def test_a_plain_application_id_is_not_sent_through_the_templar(self):
        result = _run("cpus", proxy="4", app="2", templar=_Templar({}))
        self.assertEqual(result, [2.0])

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["mem_limit"], variables={})

    def test_more_than_one_term_is_refused(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["cpus", "pids_limit"], variables={})


if __name__ == "__main__":
    unittest.main()
