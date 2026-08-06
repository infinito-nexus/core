import unittest

from utils.roles.display import display_names

APP = "web-app-nextcloud"


class TestRoleDisplayName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codec = display_names()

    def test_encode_runs_the_category_labels_together_before_the_heading(self):
        self.assertEqual(
            f"{''.join(self.codec.category_labels(APP))}·{self.codec.title(APP)}",
            self.codec.encode(APP),
        )

    def test_a_heading_longer_than_the_id_section_loses_to_it(self):
        long_heading = "svc-runner"
        self.assertGreater(
            len(self.codec.title(long_heading)),
            len(self.codec.id_fragment(long_heading)),
        )
        self.assertTrue(
            self.codec.encode(long_heading).endswith(
                f"·{self.codec.id_fragment(long_heading)}"
            ),
            self.codec.encode(long_heading),
        )
        self.assertEqual(
            "系统控制告警·compose", self.codec.encode("sys-ctl-alm-compose")
        )

    def test_the_id_section_drops_what_the_categories_already_say(self):
        self.assertEqual("nextcloud", self.codec.id_fragment(APP))
        self.assertEqual("update", self.codec.id_fragment("update"))

    def test_encode_holds_no_space_before_the_variant(self):
        self.assertNotIn(" ", self.codec.encode(APP))
        self.assertEqual(f"{self.codec.encode(APP)} 0,1", self.codec.encode(APP, "0,1"))

    def test_decode_reverses_encode_with_and_without_a_variant(self):
        for variant in ("", "0", "0,1"):
            self.assertEqual(APP, self.codec.decode(self.codec.encode(APP, variant)))

    def test_decode_passes_a_role_id_through(self):
        self.assertEqual(APP, self.codec.decode(APP))
        self.assertEqual(APP, self.codec.decode(f"{APP} 0,1"))

    def test_decode_rejects_what_names_no_role(self):
        self.assertIsNone(self.codec.decode("Update Docker image versions"))
        self.assertIsNone(self.codec.decode(""))

    def test_lists_round_trip_and_keep_sentinels(self):
        ids = f"{APP} svc-db-postgres __ALL__"
        self.assertEqual(ids, self.codec.decode_list(self.codec.encode_list(ids)))

    def test_every_role_encodes_to_one_unique_space_free_token(self):
        seen: dict[str, str] = {}
        collisions = []
        spaced = []
        for path in sorted(self.codec.roles_dir.iterdir()):
            if not (path / "README.md").is_file():
                continue
            name = self.codec.encode(path.name)
            if " " in name:
                spaced.append(f"{path.name}: {name}")
            if name in seen:
                collisions.append(f"{name}: {seen[name]} vs {path.name}")
            seen[name] = path.name
        self.assertEqual([], spaced, f"Display names that break a list: {spaced}")
        self.assertEqual([], collisions, f"Ambiguous display names: {collisions}")


if __name__ == "__main__":
    unittest.main()
