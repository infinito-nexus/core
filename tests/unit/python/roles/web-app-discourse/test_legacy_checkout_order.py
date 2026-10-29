from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

LAUNCHER = PROJECT_ROOT / "roles/web-app-discourse/tasks/03_launcher.yml"
CLEANUP = "launcher/legacy_checkout.yml"
GIT_MODULES = {"git", "ansible.builtin.git"}


def _included_file(task: dict) -> str | None:
    include = task.get("include_tasks")
    return include.get("file") if isinstance(include, dict) else include


class TestDiscourseLegacyCheckoutOrder(unittest.TestCase):
    def test_the_url_named_checkout_is_retired_before_the_clone(self) -> None:
        tasks = load_yaml_str(read_text(str(LAUNCHER)))
        cleanup = next(
            index for index, task in enumerate(tasks) if _included_file(task) == CLEANUP
        )
        clone = next(
            index for index, task in enumerate(tasks) if GIT_MODULES & task.keys()
        )
        self.assertLess(
            cleanup,
            clone,
            "the git module clones from the services directory, where git takes "
            "https://github.com/... for the old checkout's relative path "
            "https:/github.com/... and aborts with 'protocol ... is not supported' "
            "while that checkout exists",
        )


if __name__ == "__main__":
    unittest.main()
