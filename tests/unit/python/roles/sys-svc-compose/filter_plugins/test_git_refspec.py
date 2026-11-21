import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

SHA = "e2d6809b71e942a89625bfef4c69d4a3fe8f01d1"


def _load_module():
    path = (
        PROJECT_ROOT / "roles" / "sys-svc-compose" / "filter_plugins" / "git_refspec.py"
    )
    spec = importlib.util.spec_from_file_location("git_refspec_filter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestGitRefspec(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_a_tag_fetches_itself(self) -> None:
        self.assertEqual(
            self.module.git_refspec("v0.165.0", "tag"),
            "+refs/tags/v0.165.0:refs/tags/v0.165.0",
        )

    def test_a_branch_needs_no_refspec(self) -> None:
        self.assertEqual(self.module.git_refspec("v3.0.39", "branch"), "")
        self.assertEqual(self.module.git_refspec("stable/17", "branch"), "")

    def test_a_commit_fetches_its_full_sha(self) -> None:
        self.assertEqual(self.module.git_refspec(SHA, "commit"), SHA)

    def test_a_commit_that_is_no_full_sha_fails(self) -> None:
        for ref in (SHA[:7], SHA.upper(), f"{SHA}0", "v2.11.8", "main"):
            with self.subTest(ref=ref), self.assertRaises(AnsibleFilterError):
                self.module.git_refspec(ref, "commit")

    def test_an_unknown_kind_fails(self) -> None:
        for kind in ("", "Tag", "Commit", "sha", None):
            with self.subTest(kind=kind), self.assertRaises(AnsibleFilterError):
                self.module.git_refspec("v1", kind)

    def test_registered_under_its_name(self) -> None:
        filters = self.module.FilterModule().filters()
        self.assertIs(filters["git_refspec"], self.module.git_refspec)


if __name__ == "__main__":
    unittest.main()
