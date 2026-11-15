from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cli.administration.roles import declaration
from cli.administration.roles import manifest as manifest_module
from cli.administration.roles.declaration import Source
from cli.administration.roles.manifest import read_manifest
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.custom import MANIFEST_FILE

from ._fixtures import ROLE, ROLE_PATH, roles_dir, write

URL = "https://github.com/acme/widgets.git"
SHA = "5071beca9cfb32f22fab6973548931f29fae013f"


def entry(**overrides: object) -> dict:
    """Args:
        overrides: fields to replace; a ``None`` value leaves the field out.

    Returns:
        A complete manifest entry for ``ROLE`` with *overrides* applied.
    """
    fields = {"url": URL, "version": "v1.0.0", "commit": SHA, "path": ROLE_PATH}
    fields.update(overrides)
    return {name: value for name, value in fields.items() if value is not None}


class TestReadManifest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roles = roles_dir(self.root, "web-app-nextcloud")
        self.manifests = 0

    def read(self, data: object) -> tuple[dict[str, Source], list[str]]:
        self.manifests += 1
        manifest = write(
            self.root / f"checkout-{self.manifests}" / MANIFEST_FILE, json.dumps(data)
        )
        return read_manifest(manifest, self.roles)

    def assert_refused(self, data: object, *fragments: str) -> None:
        pinned, errors = self.read(data)
        message = "\n".join(errors)
        for fragment in fragments:
            self.assertIn(fragment, message)
        self.assertEqual({}, pinned)

    def test_checked_in_manifest_is_valid(self):
        pinned, errors = read_manifest(
            PROJECT_ROOT / MANIFEST_FILE, PROJECT_ROOT / "roles"
        )
        self.assertEqual([], errors)
        cosmos = pinned["web-app-cst-cosmos"]
        self.assertEqual(
            "https://github.com/kevinveenbirkenbach/cosmos.git", cosmos.url
        )
        self.assertEqual("v0.2.1", cosmos.version)
        self.assertEqual(SHA, cosmos.pinned_commit)
        self.assertEqual("ansible/roles/web-app-cst-cosmos", cosmos.path)

    def test_valid_entry_is_read_with_its_commit(self):
        pinned, errors = self.read({ROLE: entry()})
        self.assertEqual([], errors)
        self.assertEqual({ROLE: Source(URL, "v1.0.0", ROLE_PATH, SHA)}, pinned)

    def test_missing_manifest_pins_nothing(self):
        self.assertEqual(({}, []), read_manifest(self.root / "absent.yml", self.roles))

    def test_missing_field_names_role_and_field(self):
        for field in ("url", "version", "commit", "path"):
            with self.subTest(field=field):
                self.assert_refused(
                    {ROLE: entry(**{field: None})},
                    f"{ROLE}: {MANIFEST_FILE} {ROLE}.{field} is missing",
                )

    def test_release_tag_without_v_is_read(self):
        pinned, errors = self.read({ROLE: entry(version="1.0.0")})
        self.assertEqual([], errors)
        self.assertEqual("1.0.0", pinned[ROLE].version)

    def test_version_other_than_a_release_tag_is_refused(self):
        for version in ("latest", SHA, "v1.0.0-rc.1", "v1.0", "release-1.0.0"):
            with self.subTest(version=version):
                self.assert_refused(
                    {ROLE: entry(version=version)},
                    f"{ROLE}.version '{version}' is no release tag vX.Y.Z",
                )

    def test_short_commit_is_refused(self):
        self.assert_refused(
            {ROLE: entry(commit=SHA[:12])}, f"{ROLE}.commit must be the full 40-hex"
        )

    def test_url_with_credentials_is_refused_without_echoing_it(self):
        for url in (
            "https://deploy:s3cr3t@github.com/acme/widgets.git",
            "https://ghp_s3cr3t@github.com/acme/widgets.git",
        ):
            with self.subTest(url=url.split("@", 1)[1]):
                pinned, errors = self.read({ROLE: entry(url=url)})
                message = "\n".join(errors)
                self.assertIn(f"{ROLE}.url embeds credentials", message)
                self.assertNotIn("s3cr3t", message)
                self.assertEqual({}, pinned)

    def test_url_other_than_public_https_is_refused(self):
        for url in (
            "git@github.com:acme/widgets.git",
            "ssh://git@github.com/acme/widgets.git",
            "http://github.com/acme/widgets.git",
            str(self.root),
        ):
            with self.subTest(url=url):
                self.assert_refused(
                    {ROLE: entry(url=url)}, f"{ROLE}.url must be the https URL"
                )

    def test_unknown_field_is_refused(self):
        self.assert_refused(
            {ROLE: entry(tag="v1")}, f"{ROLE}.tag is not a source field"
        )

    def test_jinja_is_refused(self):
        self.assert_refused(
            {ROLE: entry(commit="{{ pin }}")}, f"{ROLE}.commit holds a Jinja expression"
        )

    def test_name_outside_the_custom_prefix_is_refused(self):
        self.assert_refused(
            {"web-app-demo": entry()}, "web-app-demo: ", "is no custom role"
        )

    def test_path_naming_another_directory_is_refused(self):
        self.assert_refused(
            {ROLE: entry(path="ansible/roles/web-app-demo")},
            "core never renames a role",
        )

    def test_entity_name_of_an_in_tree_role_is_refused(self):
        _pinned, errors = self.read(
            {"web-app-cst-nextcloud": entry(path="roles/web-app-cst-nextcloud")}
        )
        self.assertIn(
            "web-app-cst-nextcloud: entity name 'nextcloud' collides with the "
            "in-tree role web-app-nextcloud",
            "\n".join(errors),
        )

    def test_manifest_that_is_no_mapping_is_refused(self):
        self.assert_refused([ROLE], f"{MANIFEST_FILE} must map")


class TestManifestReusesTheSourceParser(unittest.TestCase):
    def test_the_046_checks_are_imported_not_restated(self):
        for name in ("parse_source", "entity_collisions", "embeds_credentials"):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(manifest_module, name), getattr(declaration, name)
                )
        source = read_text(str(manifest_module.__file__))
        for fragment in (
            "is not a source field",
            "holds a Jinja expression",
            "core never renames a role",
            "collides with the in-tree role",
            "embeds credentials",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
