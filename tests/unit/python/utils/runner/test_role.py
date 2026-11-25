from __future__ import annotations

import grp
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml
from utils.infra_inventory import POOL_ROLE
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_USERS
from utils.runner import jobs, role, store


class TestJobStacks(unittest.TestCase):
    def test_the_prefix_is_the_one_svc_runner_names_its_job_stacks_with(self) -> None:
        services = load_yaml(ROLES_DIR / POOL_ROLE / ROLE_FILE_META_SERVICES)
        self.assertEqual(services["runner"]["project_prefix"], "runner")
        self.assertEqual(role.project_prefix(), "runner")

    def test_only_the_runner_instances_count_as_job_stacks(self) -> None:
        self.assertEqual(
            [role.runner_stack(name, "runner") for name in ("runner-1", "runner-12")],
            [True, True],
        )
        for name in (
            "runner-0",
            "runner-01",
            "runner-",
            "runner-1x",
            "myrunner-1",
            "infinito-infra",
            "runner",
        ):
            with self.subTest(name=name):
                self.assertFalse(role.runner_stack(name, "runner"))

    def test_the_prefix_is_matched_literally(self) -> None:
        self.assertTrue(role.runner_stack("a.b-1", "a.b"))
        self.assertFalse(role.runner_stack("axb-1", "a.b"))


class TestQueueRefusal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "jobs"
        self.owner = load_yaml(ROLES_DIR / POOL_ROLE / ROLE_FILE_META_USERS)[
            role.QUEUE_USER
        ]
        group = mock.patch.object(
            role.grp, "getgrgid", side_effect=KeyError(self.owner["gid"])
        )
        group.start()
        self.addCleanup(group.stop)

    def test_a_gid_naming_another_group_on_the_host_is_refused_first(self) -> None:
        jobs.ensure_queue(self.root)
        taken = grp.struct_group(("docker", "x", self.owner["gid"], []))
        with mock.patch.object(role.grp, "getgrgid", return_value=taken):
            refusal = role.queue_refusal(self.root)
        self.assertEqual(len(refusal), 1)
        self.assertIn(f"gid {self.owner['gid']} is the group docker", refusal[0])
        self.assertIn("sudo groupmod -g", refusal[0])

    def test_the_group_under_its_own_name_passes(self) -> None:
        jobs.ensure_queue(self.root)
        own = grp.struct_group((self.owner["username"], "x", self.owner["gid"], []))
        with mock.patch.object(role.grp, "getgrgid", return_value=own):
            self.assertEqual(role.queue_refusal(self.root), [])

    def test_a_missing_queue_names_the_target_that_creates_it(self) -> None:
        refusal = role.queue_refusal(self.root)
        self.assertEqual(len(refusal), 1)
        self.assertIn("make infra-update", refusal[0])

    def test_a_writable_queue_with_a_sound_layout_passes(self) -> None:
        jobs.ensure_queue(self.root)
        self.assertEqual(role.queue_refusal(self.root), [])

    def test_a_root_without_the_sticky_bit_is_refused(self) -> None:
        jobs.ensure_queue(self.root)
        self.root.chmod(store.SHARED_DIR_MODE)
        refusal = role.queue_refusal(self.root)
        self.assertEqual(len(refusal), 1)
        self.assertIn("lacks the sticky bit", refusal[0])
        self.assertIn("make infra-update", refusal[0])

    def test_a_symlinked_jobs_folder_is_refused(self) -> None:
        jobs.ensure_queue(self.root)
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.root / "jobs").rmdir()
        (self.root / "jobs").symlink_to(elsewhere)
        refusal = role.queue_refusal(self.root)
        self.assertEqual(len(refusal), 1)
        self.assertIn(f"{self.root / 'jobs'} is a link", refusal[0])

    def test_a_queue_without_its_folders_is_refused(self) -> None:
        self.root.mkdir()
        self.root.chmod(store.QUEUE_ROOT_MODE)
        self.assertEqual(len(role.queue_refusal(self.root)), len(store.QUEUE_DIRS))

    @unittest.skipIf(os.geteuid() == 0, "root writes every directory")
    def test_an_unwritable_queue_names_the_group_to_join(self) -> None:
        self.root.mkdir()
        self.root.chmod(0o550)
        self.addCleanup(self.root.chmod, 0o750)
        refusal = role.queue_refusal(self.root)
        self.assertEqual(len(refusal), 1)
        self.assertIn(f"sudo usermod -aG {self.owner['username']}", refusal[0])
        self.assertIn(f"gid {self.owner['gid']}", refusal[0])
        self.assertIn("grants root on this host", refusal[0])


if __name__ == "__main__":
    unittest.main()
