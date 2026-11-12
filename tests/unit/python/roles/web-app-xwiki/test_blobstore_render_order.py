from __future__ import annotations

import unittest
from typing import Any

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ROLE = PROJECT_ROOT / "roles/web-app-xwiki"
BOOTSTRAP = ROLE / "tasks/00_core.yml"
MANAGER_OPS = ROLE / "tasks/02_manager_ops.yml"
SWITCH = "xwiki_blobstore_s3_enabled_switch"
DESIGN = "06_design.yml"


def flatten(tasks: Any) -> list[dict[str, Any]]:
    """Return every task of a task file in the order Ansible reaches it.

    Args:
        tasks: a parsed task list whose entries may nest under
            ``block`` / ``rescue`` / ``always``.

    Returns:
        The tasks as a flat list, each parent before its children.
    """
    flat: list[dict[str, Any]] = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        flat.append(task)
        for key in ("block", "rescue", "always"):
            flat.extend(flatten(task.get(key)))
    return flat


def switch_of(task: dict[str, Any]) -> Any:
    """Return the blob-store switch a task sets, or ``False`` when it sets none.

    Args:
        task: one parsed task mapping.

    Returns:
        The value bound to the switch, else ``False``.
    """
    return (task.get("vars") or {}).get(SWITCH, False)


class TestBlobstoreRenderOrder(unittest.TestCase):
    def test_the_bootstrap_render_never_selects_the_bucket(self) -> None:
        for task in flatten(load_yaml_str(read_text(str(BOOTSTRAP)))):
            if SWITCH in (task.get("vars") or {}):
                self.assertIs(
                    switch_of(task),
                    False,
                    "nothing answers to the 's3' blob store hint before "
                    "04_extensions installs xwiki-commons-store-blob-s3, so a "
                    "bootstrap render that selects the bucket leaves a wiki whose "
                    "data volume was dropped unable to start at all",
                )

    def test_the_bucket_render_precedes_every_attachment_read(self) -> None:
        tasks = flatten(load_yaml_str(read_text(str(MANAGER_OPS))))
        renders = [i for i, task in enumerate(tasks) if switch_of(task) is not False]
        design = [
            i
            for i, task in enumerate(tasks)
            if str(task.get("include_tasks") or "").endswith(DESIGN)
        ]
        self.assertTrue(renders, f"no render in {MANAGER_OPS.name} selects the bucket")
        self.assertTrue(design, f"no task in {MANAGER_OPS.name} includes {DESIGN}")
        self.assertLess(
            min(renders),
            min(design),
            "06_design/logo.yml GETs an attachment and accepts only 200 or 404, so "
            "every deploy that still points the wiki at the empty filesystem blob "
            "store answers 500 there and dies after 31 retries",
        )


if __name__ == "__main__":
    unittest.main()
