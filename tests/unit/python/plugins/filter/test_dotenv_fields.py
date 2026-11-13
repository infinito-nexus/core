import json
import unittest

import jinja2
from ansible.errors import AnsibleFilterError

from plugins.filter.dotenv import FilterModule, dotenv_names


class TestDotenvFields(unittest.TestCase):
    def setUp(self):
        env = jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False)
        )
        env.filters.update(FilterModule().filters())
        self.env = env

    def _held(self, content, fields, mode="compose"):
        template = self.env.from_string(
            "{{ content | dotenv_fields(fields) | tojson }}"
        )
        return json.loads(
            template.render(content=content, fields=fields, DEPLOYMENT_MODE=mode)
        )

    def test_each_field_reads_its_upper_case_variable(self):
        content = 'GF_USERS_ALLOW_SIGN_UP="false"\nGF_AUTH_BASIC_ENABLED=true\n'
        self.assertEqual(
            {"gf_users_allow_sign_up": "false", "gf_auth_basic_enabled": "true"},
            self._held(content, ["gf_users_allow_sign_up", "gf_auth_basic_enabled"]),
        )

    def test_a_field_the_file_does_not_assign_is_left_out(self):
        self.assertEqual({}, self._held("OTHER=1\n", ["gf_users_allow_sign_up"]))

    def test_an_empty_assignment_is_read_as_empty(self):
        self.assertEqual({"key": ""}, self._held("KEY=\n", ["key"]))

    def test_a_longer_variable_with_the_same_prefix_does_not_match(self):
        self.assertEqual({}, self._held("KEY_EXTRA=1\n", ["key"]))

    def test_what_dotenv_quote_writes_reads_back_in_both_modes(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                written = self.env.from_string("KEY={{ value | dotenv_quote }}").render(
                    value='p$a"ss', DEPLOYMENT_MODE=mode
                )
                self.assertEqual({"key": 'p$a"ss'}, self._held(written, ["key"], mode))

    def test_no_content_holds_nothing(self):
        self.assertEqual({}, self._held(None, ["key"]))

    def test_a_field_that_is_not_lower_snake_case_fails_loud(self):
        for field in ("GF_AUTH", "gfAuthBasic", "gf-auth", "1gf", "gf|x"):
            with self.subTest(field=field):
                with self.assertRaises(AnsibleFilterError):
                    self._held("GF_AUTH=1\n", [field])
                with self.assertRaises(AnsibleFilterError):
                    dotenv_names([field])

    def test_the_names_are_the_upper_cased_fields_in_order(self):
        self.assertEqual(
            ["GF_AUTH_BASIC_ENABLED", "MM_SITE"],
            dotenv_names(["gf_auth_basic_enabled", "mm_site"]),
        )


if __name__ == "__main__":
    unittest.main()
