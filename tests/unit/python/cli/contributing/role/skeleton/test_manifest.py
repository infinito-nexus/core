from __future__ import annotations

import unittest

from cli.contributing.role.skeleton.manifest import fields, validate


def _manifest(**overrides):
    data = {
        "name": "notes",
        "description": "Self-hosted note taking web application",
        "homepage": "https://example.org/",
        "license": "MIT",
        "image": "ghcr.io/example/notes:1.2.3",
        "port": 8080,
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def _errors(**overrides) -> list[str]:
    return validate(_manifest(**overrides))[1]


class TestValidManifest(unittest.TestCase):
    def test_a_complete_manifest_validates(self):
        manifest, errors = validate(_manifest())
        self.assertEqual([], errors)
        self.assertEqual("notes", manifest.name)

    def test_the_image_splits_into_repository_and_tag(self):
        manifest, _ = validate(_manifest())
        self.assertEqual(
            ("ghcr.io/example/notes", "1.2.3"), (manifest.repository, manifest.version)
        )

    def test_a_registry_port_stays_in_the_repository(self):
        manifest, _ = validate(_manifest(image="registry.example.org:5000/notes:2"))
        self.assertEqual("registry.example.org:5000/notes", manifest.repository)

    def test_omitted_optional_fields_take_their_defaults(self):
        manifest, _ = validate(_manifest())
        self.assertEqual(
            ("none", "none", (), (), ()),
            (
                manifest.database,
                manifest.login,
                manifest.features,
                manifest.environment,
                manifest.volumes,
            ),
        )

    def test_the_list_form_of_environment_equals_the_mapping_form(self):
        listed, _ = validate(_manifest(environment=["MODE=prod", "URL=a=b"]))
        mapped, _ = validate(_manifest(environment={"MODE": "prod", "URL": "a=b"}))
        self.assertEqual(mapped.environment, listed.environment)

    def test_a_volume_path_becomes_a_volume_key(self):
        manifest, _ = validate(_manifest(volumes=["/var/lib/notes/"]))
        self.assertEqual(
            ("var_lib_notes", "/var/lib/notes"),
            (manifest.volumes[0].key, manifest.volumes[0].path),
        )


class TestInvalidManifest(unittest.TestCase):
    def test_a_missing_required_field_is_named(self):
        self.assertEqual(["image: required"], _errors(image=None))

    def test_a_name_outside_the_charset_is_refused(self):
        self.assertTrue(_errors(name="Notes_App")[0].startswith("name:"))

    def test_a_name_with_a_double_dash_is_refused(self):
        self.assertTrue(_errors(name="notes--app")[0].startswith("name:"))

    def test_an_image_without_a_tag_is_refused(self):
        self.assertTrue(_errors(image="ghcr.io/example/notes")[0].startswith("image:"))

    def test_a_port_above_the_range_is_refused(self):
        self.assertTrue(_errors(port=65536)[0].startswith("port:"))

    def test_a_port_of_zero_is_refused(self):
        self.assertTrue(_errors(port=0)[0].startswith("port:"))

    def test_a_boolean_port_is_refused(self):
        self.assertTrue(_errors(port=True)[0].startswith("port:"))

    def test_an_unknown_database_is_refused(self):
        self.assertTrue(_errors(database="sqlite")[0].startswith("database:"))

    def test_an_unknown_login_is_refused(self):
        self.assertTrue(_errors(login="saml")[0].startswith("login:"))

    def test_an_unknown_feature_is_refused(self):
        self.assertTrue(_errors(features=["email", "kafka"])[0].startswith("features:"))

    def test_a_description_over_the_limit_is_refused(self):
        self.assertTrue(_errors(description="x" * 121)[0].startswith("description:"))

    def test_a_description_starting_with_a_verb_is_refused(self):
        self.assertTrue(
            _errors(description="Runs a note app")[0].startswith("description:")
        )

    def test_a_description_with_a_trailing_period_is_refused(self):
        self.assertTrue(_errors(description="Note app.")[0].startswith("description:"))

    def test_a_licence_outside_the_table_is_refused(self):
        self.assertTrue(_errors(license="NOT-A-LICENCE")[0].startswith("license:"))

    def test_a_homepage_without_scheme_is_refused(self):
        self.assertTrue(_errors(homepage="example.org")[0].startswith("homepage:"))

    def test_an_http_homepage_is_refused_for_login_oidc_only(self):
        self.assertTrue(
            _errors(homepage="http://example.org/", login="oidc")[0].startswith(
                "homepage:"
            )
        )
        self.assertEqual([], _errors(homepage="http://example.org/", login="none"))

    def test_jinja_in_a_free_text_field_is_refused(self):
        self.assertTrue(
            _errors(description="Note {{ app }}")[0].startswith("description:")
        )

    def test_an_unknown_field_is_refused(self):
        self.assertEqual(["colour: unknown field"], _errors(colour="blue"))

    def test_an_environment_key_outside_the_charset_is_refused(self):
        self.assertTrue(
            _errors(environment={"mode": "x"})[0].startswith("environment:")
        )

    def test_a_relative_volume_path_is_refused(self):
        self.assertTrue(_errors(volumes=["data"])[0].startswith("volumes:"))

    def test_two_volume_paths_on_one_key_are_refused(self):
        self.assertTrue(_errors(volumes=["/a/b", "/a-b"])[0].startswith("volumes:"))

    def test_a_non_mapping_manifest_is_refused(self):
        self.assertEqual(
            (None, ["manifest: must be a mapping of the fields the schema lists"]),
            validate([]),
        )

    def test_every_error_line_names_its_field(self):
        errors = _errors(
            name="X", image="x", port=-1, database="x", login="x", features=["x"]
        )
        known = {item.name for item in fields()}
        self.assertEqual(set(), {line.split(":", 1)[0] for line in errors} - known)


STATIC = {
    "kind": "static",
    "name": "builder",
    "description": "Site that turns applications into Infinito.Nexus roles",
    "license": "MIT",
}


class TestStaticKind(unittest.TestCase):
    def test_name_description_and_licence_suffice(self):
        manifest, errors = validate(STATIC)
        self.assertEqual([], errors)
        self.assertEqual(("static", "builder"), (manifest.kind, manifest.name))

    def test_a_container_field_is_refused_by_name(self):
        self.assertEqual(
            ["image: only for kind container"],
            validate({**STATIC, "image": "ghcr.io/example/site:1"})[1],
        )

    def test_the_container_fields_keep_their_defaults(self):
        manifest, _ = validate(STATIC)
        self.assertEqual(
            ("", 0, "none", "none", ()),
            (
                manifest.repository,
                manifest.port,
                manifest.database,
                manifest.login,
                manifest.volumes,
            ),
        )

    def test_an_unknown_kind_is_refused(self):
        self.assertTrue(_errors(kind="vm")[0].startswith("kind:"))

    def test_an_omitted_kind_is_a_container(self):
        self.assertEqual("container", validate(_manifest())[0].kind)


class TestFields(unittest.TestCase):
    def test_every_field_names_the_kinds_it_belongs_to(self):
        self.assertEqual(
            {"container", "static"},
            {kind for item in fields() for kind in item.as_json()["kinds"]},
        )

    def test_required_fields_carry_no_default(self):
        self.assertEqual(
            ["name", "description", "homepage", "license", "image", "port"],
            [item.name for item in fields() if item.required],
        )

    def test_the_licence_choices_are_the_licence_table(self):
        licence = next(item for item in fields() if item.name == "license")
        self.assertIn("MIT", licence.choices)


if __name__ == "__main__":
    unittest.main()
