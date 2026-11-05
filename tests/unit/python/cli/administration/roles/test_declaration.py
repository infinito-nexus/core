from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cli.administration.roles.declaration import Source, read_declarations

from ._fixtures import ROLE, ROLE_PATH, declaration, inventory, roles_dir, write

GIT_URL = "https://github.com/acme/widgets.git"


class TestReadDeclarations(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roles = roles_dir(self.root, "web-app-nextcloud")

    def read(self, applications: dict, groups: tuple[str, ...] = (ROLE,)):
        inv = inventory(self.root / "inventory", list(groups), applications)
        return read_declarations(inv, self.roles)

    def assert_refused(self, applications: dict, *fragments: str, groups=(ROLE,)):
        declared, errors = self.read(applications, groups)
        message = "\n".join(errors)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return declared

    def test_complete_declaration_is_read(self):
        declared, errors = self.read({ROLE: declaration(GIT_URL)})
        self.assertEqual([], errors)
        self.assertEqual({ROLE: Source(GIT_URL, "v1.0.0", ROLE_PATH)}, declared)

    def test_ssh_url_is_accepted(self):
        _declared, errors = self.read(
            {ROLE: declaration("git@github.com:acme/widgets.git")}
        )
        self.assertEqual([], errors)

    def test_ssh_config_host_alias_is_accepted(self):
        _declared, errors = self.read(
            {ROLE: declaration("github-store:acme/widgets.git")}
        )
        self.assertEqual([], errors)

    def test_plain_http_url_is_refused(self):
        self.assert_refused(
            {ROLE: declaration("http://github.com/acme/widgets.git")},
            ROLE,
            "source.url is neither",
        )

    def test_missing_url_names_group_and_field(self):
        applications = {
            ROLE: {"custom": True, "source": {"version": "v1", "path": ROLE_PATH}}
        }
        declared = self.assert_refused(applications, ROLE, "source.url is missing")
        self.assertEqual({}, declared)

    def test_missing_version_of_a_git_url_names_the_field(self):
        self.assert_refused(
            {ROLE: declaration(GIT_URL, version=None)},
            ROLE,
            "source.version is missing",
        )

    def test_missing_path_names_the_field(self):
        applications = {
            ROLE: {"custom": True, "source": {"url": GIT_URL, "version": "v1"}}
        }
        self.assert_refused(applications, ROLE, "source.path is missing")

    def test_missing_source_names_the_field(self):
        self.assert_refused(
            {ROLE: {"custom": True}}, ROLE, f"applications.{ROLE}.source is missing"
        )

    def test_local_directory_needs_no_version(self):
        declared, errors = self.read({ROLE: declaration(str(self.root), version=None)})
        self.assertEqual([], errors)
        self.assertTrue(declared[ROLE].local)
        self.assertIsNone(declared[ROLE].version)

    def test_url_that_is_neither_git_nor_absolute_is_refused(self):
        self.assert_refused(
            {ROLE: declaration("checkouts/widgets")}, ROLE, "source.url is neither"
        )

    def test_url_with_credentials_is_refused_without_echoing_it(self):
        for url in (
            "https://deploy:s3cr3t@github.com/acme/widgets.git",
            "https://ghp_s3cr3t@github.com/acme/widgets.git",
            "ssh://git:s3cr3t@github.com/acme/widgets.git",
        ):
            with self.subTest(url=url.split("@", 1)[1]):
                declared, errors = self.read({ROLE: declaration(url)})
                message = "\n".join(errors)
                self.assertIn(
                    f"{ROLE}: applications.{ROLE}.source.url embeds credentials",
                    message,
                )
                self.assertNotIn("s3cr3t", message)
                self.assertEqual({}, declared)

    def test_ssh_user_without_password_is_no_credential(self):
        _declared, errors = self.read(
            {ROLE: declaration("ssh://git@github.com/acme/widgets.git")}
        )
        self.assertEqual([], errors)

    def test_jinja_in_a_source_field_is_refused(self):
        applications = {ROLE: declaration("{{ lookup('env', 'ROLE_URL') }}")}
        self.assert_refused(applications, ROLE, "source.url holds a Jinja expression")

    def test_jinja_in_custom_is_refused(self):
        applications = {ROLE: {**declaration(GIT_URL), "custom": "{{ true }}"}}
        declared = self.assert_refused(
            applications, ROLE, f"{ROLE}.custom holds a Jinja expression"
        )
        self.assertEqual({}, declared)

    def test_unknown_source_field_is_refused(self):
        applications = {ROLE: declaration(GIT_URL)}
        applications[ROLE]["source"]["tag"] = "v1"
        self.assert_refused(applications, ROLE, "source.tag is not a source field")

    def test_path_leaving_the_repository_is_refused(self):
        applications = {ROLE: declaration(GIT_URL, path=f"../{ROLE}")}
        self.assert_refused(applications, ROLE, "relative path inside the repository")

    def test_directory_name_other_than_the_group_names_both(self):
        applications = {ROLE: declaration(GIT_URL, path="ansible/roles/web-app-demo")}
        self.assert_refused(
            applications, "'web-app-demo'", f"'{ROLE}'", "never renames"
        )

    def test_group_without_custom_true_is_refused(self):
        self.assert_refused(
            {}, f"{ROLE}: inventory group without applications.{ROLE}.custom: true"
        )

    def test_custom_false_counts_as_undeclared(self):
        applications = {ROLE: {**declaration(GIT_URL), "custom": False}}
        declared = self.assert_refused(applications, f"{ROLE}: inventory group without")
        self.assertEqual({}, declared)

    def test_custom_true_outside_the_prefix_is_refused(self):
        applications = {"web-app-demo": declaration(GIT_URL)}
        self.assert_refused(
            applications, "web-app-demo: custom: true marks a group outside", groups=()
        )

    def test_entity_name_of_an_in_tree_role_is_refused(self):
        applications = {
            "web-app-cst-nextcloud": declaration(
                GIT_URL, path="roles/web-app-cst-nextcloud"
            )
        }
        self.assert_refused(
            applications,
            "web-app-cst-nextcloud: entity name 'nextcloud'",
            "in-tree role web-app-nextcloud",
            groups=("web-app-cst-nextcloud",),
        )

    def test_declarations_that_differ_between_files_are_refused(self):
        write(
            self.root / "inventory/group_vars/all.yml",
            json.dumps(
                {"applications": {ROLE: declaration(GIT_URL, version="v2.0.0")}}
            ),
        )
        self.assert_refused(
            {ROLE: declaration(GIT_URL)}, f"applications.{ROLE}.source differs between"
        )

    def read_yaml(self, host_vars: str):
        base = self.root / "inventory"
        write(base / "host_vars/localhost.yml", host_vars)
        devices = {"all": {"children": {ROLE: {"hosts": {"localhost": {}}}}}}
        return read_declarations(
            write(base / "devices.yml", json.dumps(devices)), self.roles
        )

    def test_tagged_custom_is_refused_naming_the_tag(self):
        declared, errors = self.read_yaml(
            f"applications:\n  {ROLE}:\n    custom: !vault |\n"
            "      $ANSIBLE_VAULT;1.1;AES256\n      6162\n"
        )
        self.assertEqual({}, declared)
        self.assertIn(
            f"{ROLE}: applications.{ROLE}.custom holds a !vault value",
            "\n".join(errors),
        )

    def test_tagged_source_field_is_refused_naming_the_tag(self):
        declared, errors = self.read_yaml(
            f"applications:\n  {ROLE}:\n    custom: true\n    source:\n"
            f"      url: {GIT_URL}\n      version: !unsafe v1.0.0\n      path: {ROLE_PATH}\n"
        )
        self.assertEqual({}, declared)
        self.assertIn(
            f"{ROLE}: applications.{ROLE}.source.version holds a !unsafe value",
            "\n".join(errors),
        )

    def test_unparsable_file_declares_nothing_and_is_the_only_error(self):
        broken = write(self.root / "inventory/group_vars/all.yml", "applications: [\n")
        declared, errors = self.read({ROLE: declaration(GIT_URL)})
        self.assertEqual({}, declared)
        self.assertEqual(1, len(errors))
        self.assertTrue(errors[0].startswith(f"{broken}: cannot read"), errors[0])

    def test_settings_without_custom_in_another_file_do_not_conflict(self):
        write(
            self.root / "inventory/group_vars/all.yml",
            json.dumps(
                {"applications": {ROLE: {"services": {"web": {"enabled": True}}}}}
            ),
        )
        _declared, errors = self.read({ROLE: declaration(GIT_URL)})
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
