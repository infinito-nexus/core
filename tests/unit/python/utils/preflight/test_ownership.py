import unittest

from utils.preflight.ownership import labelled_ownership_errors, parse_labelled

DECLARED = {
    "matomo": [("web-app-matomo", "matomo")],
    "matomo_data": [("web-app-matomo", "matomo")],
    "redis": [("svc-db-redis", "redis"), ("web-app-nextcloud", "nextcloud")],
}


class TestParseLabelled(unittest.TestCase):
    def test_lines_split_into_name_project_and_namespace(self):
        output = "matomo\tmatomo\t\nmatomo_matomo.1.abc\t\tmatomo\n\n"
        self.assertEqual(
            parse_labelled(output),
            [("matomo", "matomo", ""), ("matomo_matomo.1.abc", "", "matomo")],
        )

    def test_a_container_with_several_names_yields_each(self):
        self.assertEqual(
            parse_labelled("matomo,web/matomo\tmatomo\t"),
            [("matomo", "matomo", ""), ("web/matomo", "matomo", "")],
        )

    def test_a_line_without_three_fields_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_labelled("matomo matomo")


class TestLabelledOwnershipErrors(unittest.TestCase):
    def test_objects_labelled_with_their_entity_pass(self):
        objects = [
            ("matomo", "matomo", ""),
            ("matomo_data", "", "matomo"),
        ]
        self.assertEqual(labelled_ownership_errors("volume", objects, DECLARED), [])

    def test_undeclared_objects_pass_whatever_their_labels(self):
        objects = [("legacy", "", ""), ("bridge-helper", "other", "")]
        self.assertEqual(labelled_ownership_errors("container", objects, DECLARED), [])

    def test_any_declaring_entity_is_accepted(self):
        objects = [("redis", "nextcloud", "")]
        self.assertEqual(labelled_ownership_errors("container", objects, DECLARED), [])

    def test_a_foreign_project_names_the_owner(self):
        objects = [("matomo", "nextcloud", "")]
        self.assertEqual(
            labelled_ownership_errors("container", objects, DECLARED),
            [
                (
                    "container 'matomo' belongs to compose project 'nextcloud', "
                    "but it is the container of web-app-matomo (entity 'matomo')"
                )
            ],
        )

    def test_a_container_without_labels_fails(self):
        objects = [("matomo", "", "")]
        self.assertEqual(
            labelled_ownership_errors("container", objects, DECLARED),
            [
                (
                    "container 'matomo' belongs to no compose project or stack, "
                    "but it is the container of web-app-matomo (entity 'matomo')"
                )
            ],
        )

    def test_a_volume_without_any_label_passes(self):
        objects = [("matomo_data", "", "")]
        self.assertEqual(labelled_ownership_errors("volume", objects, DECLARED), [])

    def test_a_volume_of_a_foreign_project_fails(self):
        objects = [("matomo_data", "nextcloud", "")]
        self.assertEqual(
            labelled_ownership_errors("volume", objects, DECLARED),
            [
                (
                    "volume 'matomo_data' belongs to compose project 'nextcloud', "
                    "but it is the volume of web-app-matomo (entity 'matomo')"
                )
            ],
        )

    def test_both_foreign_labels_and_every_owner_are_named(self):
        objects = [("redis", "mailu", "mailu")]
        self.assertEqual(
            labelled_ownership_errors("container", objects, DECLARED),
            [
                (
                    "container 'redis' belongs to compose project 'mailu' and stack 'mailu', "
                    "but it is the container of svc-db-redis (entity 'redis') or "
                    "web-app-nextcloud (entity 'nextcloud')"
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
