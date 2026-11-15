import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text

README = PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / "README.md"


class TestSeaweedfsReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_buckets(self):
        text = read_text(str(README))
        for fact in (
            "## Workspace buckets",
            "`ws-<id>-state`",
            "`ws-<id>-provision`",
            "exactly `Read`, `Write` and `List`",
            "`identities.d/ws-<id>.json`, mode `0600`",
            "`tenant/data/ws-<id>-provision/s3`",
            "### Fail-closed reload",
            "`SIGHUP`",
            "never the file alone",
            "### Slot maximum",
            "`services.seaweedfs.workspaces.max`",
            "### Version floor",
            "4.53 or later",
            "refuses while the bucket still holds a `.tfstate` object",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)


if __name__ == "__main__":
    unittest.main()
