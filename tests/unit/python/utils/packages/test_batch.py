import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.packages.batch import batch_ids, batch_ids_by_role


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml(str(path), payload)


class TestBatchIds(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _write(
            self.root,
            "meta/packages.yml",
            {
                "git": {"Debian": ["git"]},
                "postfix": {"Debian": ["postfix"], "batch": False},
            },
        )

    def test_a_role_batches_its_own_ids(self):
        _write(self.root, "roles/role-a/meta/packages.yml", {"jq": {"Debian": ["jq"]}})
        self.assertEqual(batch_ids(["role-a"], self.root), ["jq"])

    def test_an_unbatched_own_id_is_left_to_the_role(self):
        _write(
            self.root,
            "roles/role-a/meta/packages.yml",
            {"jq": {"Debian": ["jq"], "batch": False}},
        )
        self.assertEqual(batch_ids(["role-a"], self.root), [])

    def test_a_referenced_shared_id_is_batched_with_the_role(self):
        _write(self.root, "roles/role-a/meta/packages.yml", {"git": {"shared": True}})
        self.assertEqual(batch_ids(["role-a"], self.root), ["git"])

    def test_a_referenced_unbatched_shared_id_stays_out(self):
        _write(
            self.root, "roles/role-a/meta/packages.yml", {"postfix": {"shared": True}}
        )
        self.assertEqual(batch_ids(["role-a"], self.root), [])

    def test_shared_ids_nobody_references_stay_out(self):
        self.assertEqual(batch_ids(["role-a"], self.root), [])

    def test_roles_outside_the_deploy_contribute_nothing(self):
        _write(self.root, "roles/role-a/meta/packages.yml", {"jq": {"Debian": ["jq"]}})
        _write(
            self.root, "roles/role-b/meta/packages.yml", {"curl": {"Debian": ["curl"]}}
        )
        self.assertEqual(batch_ids(["role-a"], self.root), ["jq"])

    def test_ids_are_sorted_and_unique(self):
        _write(
            self.root,
            "roles/role-a/meta/packages.yml",
            {"jq": {"Debian": ["jq"]}, "git": {"shared": True}},
        )
        _write(self.root, "roles/role-b/meta/packages.yml", {"git": {"shared": True}})
        self.assertEqual(batch_ids(["role-b", "role-a"], self.root), ["git", "jq"])

    def test_ids_are_grouped_by_role(self):
        _write(self.root, "roles/role-a/meta/packages.yml", {"jq": {"Debian": ["jq"]}})
        self.assertEqual(batch_ids_by_role(self.root), {"role-a": {"jq"}})


if __name__ == "__main__":
    unittest.main()
