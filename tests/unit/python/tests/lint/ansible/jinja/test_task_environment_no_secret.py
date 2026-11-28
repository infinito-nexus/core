"""Negative controls for the task-environment credential lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.jinja import test_task_environment_no_secret as lint


def _task(entries: str) -> str:
    return "- ansible.builtin.command: tool\n  environment:\n" + entries


class TestStillConvicted(unittest.TestCase):
    def test_a_password_name_with_a_password_value(self) -> None:
        content = _task('    DB_PASSWORD: "{{ X_PASSWORD }}"\n')
        self.assertEqual([(3, "DB_PASSWORD")], lint.scan_environment(content, {}))

    def test_a_signing_key_from_a_key_variable(self) -> None:
        content = _task('    SIGNING_KEY: "{{ SOME_KEY }}"\n')
        self.assertEqual([(3, "SIGNING_KEY")], lint.scan_environment(content, {}))

    def test_a_signing_key_from_more_than_a_lone_path_variable(self) -> None:
        for value in (
            "{{ A_PATH }}-{{ B_SECRET }}",
            "{{ A_PATH | b64encode }}",
            "{{ x.signing_path }}",
        ):
            with self.subTest(value=value):
                content = _task(f'    SIGNING_KEY: "{value}"\n')
                self.assertEqual(
                    [(3, "SIGNING_KEY")], lint.scan_environment(content, {})
                )

    def test_a_task_level_password(self) -> None:
        content = (
            "- name: x\n"
            "  ansible.builtin.shell: tool\n"
            "  environment:\n"
            '    X_VALUE: "{{ x_admin_password }}"\n'
        )
        self.assertEqual([(4, "X_VALUE")], lint.scan_environment(content, {}))

    def test_a_block_level_password(self) -> None:
        content = (
            "- block:\n"
            "    - block:\n"
            "        - ansible.builtin.command: tool\n"
            "      environment:\n"
            '        ADMIN_PASSWORD: "{{ x_admin }}"\n'
            "  environment:\n"
            '    ROOT_PASSWORD: "{{ x_root }}"\n'
        )
        self.assertEqual(
            [(5, "ADMIN_PASSWORD"), (7, "ROOT_PASSWORD")],
            lint.scan_environment(content, {}),
        )

    def test_a_play_role_entry_and_an_include_apply(self) -> None:
        content = (
            "- hosts: all\n"
            "  roles:\n"
            "    - role: x\n"
            "      environment:\n"
            '        X_TOKEN: "{{ x_token }}"\n'
            "  tasks:\n"
            "    - ansible.builtin.include_tasks:\n"
            "        file: x.yml\n"
            "        apply:\n"
            "          environment:\n"
            '            X_SECRET: "{{ x_secret }}"\n'
        )
        self.assertEqual(
            [(5, "X_TOKEN"), (11, "X_SECRET")], lint.scan_environment(content, {})
        )

    def test_a_variable_that_only_contains_attr_still_convicts(self) -> None:
        content = _task('    X_VALUE: "{{ X_PASSWORD_ATTRS }}"\n')
        self.assertEqual([(3, "X_VALUE")], lint.scan_environment(content, {}))


ATTRIBUTE_DEFINITIONS = {"X_LDAP_PASSWORD_ATTR": [" LDAP.USER.ATTRIBUTES.PASSWORD "]}


class TestIamShapesPass(unittest.TestCase):
    def test_an_attribute_name_is_no_credential(self) -> None:
        content = _task(
            '    X_LDAP_PASSWORD_ATTR: "{{ X_LDAP_PASSWORD_ATTR }}"\n'
            '    X_LDAP_PASSWORD_ATTRIBUTE: "{{ X_LDAP_PASSWORD_ATTRIBUTE }}"\n'
        )
        self.assertEqual([], lint.scan_environment(content, ATTRIBUTE_DEFINITIONS))

    def test_an_attribute_inside_a_scalar_environment_is_no_credential(self) -> None:
        content = (
            "- ansible.builtin.set_fact:\n"
            "    x_auth_env:\n"
            '      X_LDAP_PASSWORD_ATTR: "{{ X_LDAP_PASSWORD_ATTR }}"\n'
            "- ansible.builtin.shell: run\n"
            "  environment: \"{{ x_auth_env | combine({'PHASE': 'x'}) }}\"\n"
        )
        self.assertEqual([], lint.scan_environment(content, ATTRIBUTE_DEFINITIONS))

    def test_a_path_under_a_strong_name_is_no_credential(self) -> None:
        definitions = {
            "X_SIGNING_KEY_PATH": [
                " [X_DATA_PATH, X_DOMAIN ~ '.signing.key'] | path_join "
            ]
        }
        content = _task('    X_SIGNING_KEY: "{{ X_SIGNING_KEY_PATH }}"\n')
        self.assertEqual([], lint.scan_environment(content, definitions))

    def test_an_environment_key_inside_vars_is_data(self) -> None:
        content = (
            "- block:\n"
            "    - ansible.builtin.command: tool\n"
            "      vars:\n"
            "        x_deploy:\n"
            "          environment:\n"
            '            vault_password: "{{ X_VAULT_PASSWORD }}"\n'
            "      module_defaults:\n"
            "        ansible.builtin.uri:\n"
            "          environment:\n"
            '            X_TOKEN: "{{ x_token }}"\n'
            "    - ansible.builtin.uri:\n"
            "        body:\n"
            "          environment:\n"
            '            X_SECRET: "{{ x_secret }}"\n'
        )
        self.assertEqual([], lint.scan_environment(content, {}))


class TestUrlPathSegments(unittest.TestCase):
    def test_a_path_segment_in_the_literal_around_the_jinja_passes(self) -> None:
        content = _task('    HTTP_URL: "{{ X_NETNS_URL }}/api/v1/users/token"\n')
        self.assertEqual([], lint.scan_environment(content, {}))

    def test_a_path_segment_in_a_string_literal_of_the_jinja_passes(self) -> None:
        content = _task(
            "    HTTP_URL: \"{{ [X_PAGES, 'objects/XWiki.XWikiUsers/0/properties/password']"
            ' | url_join }}"\n'
        )
        self.assertEqual([], lint.scan_environment(content, {}))

    def test_a_path_segment_reached_through_include_vars_passes(self) -> None:
        content = (
            "- ansible.builtin.include_tasks: http.yml\n"
            "  vars:\n"
            '    x_http_url: "{{ [X_PAGES, X_ADMIN_USER | urlencode,'
            " 'objects/XWiki.XWikiUsers/0/properties/password'] | url_join }}\"\n"
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    HTTP_URL: "{{ x_http_url }}"\n'
        )
        self.assertEqual([], lint.scan_environment(content, {}))

    def test_a_credential_word_outside_a_path_segment_still_convicts(self) -> None:
        for value in (
            "https://user:password@{{ x_host }}/",
            "{{ x_base }}/api?token=abc",
            "{{ x_base }}/login?user=a&password=x",
            "Authorization: Bearer {{ x_token }}",
            "{{ x_base }}/{{ x_api_token }}",
            "{{ x_base ~ '/' ~ x_api_token }}",
        ):
            with self.subTest(value=value):
                content = _task(f'    X_VALUE: "{value}"\n')
                self.assertEqual([(3, "X_VALUE")], lint.scan_environment(content, {}))


if __name__ == "__main__":
    unittest.main()
