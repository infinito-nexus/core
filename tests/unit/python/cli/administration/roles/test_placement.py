from __future__ import annotations

import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.roles import placement
from cli.administration.roles.marker import MARKER_FILE, is_placed
from cli.administration.roles.placement import clean, pull
from utils.cache.files import read_text
from utils.roles.custom import CustomRoleError
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

from ._fixtures import (
    ROLE,
    ROLE_PATH,
    declaration,
    git,
    inventory,
    local_role,
    role_repo,
    roles_dir,
    write,
)

OTHER = "web-app-cst-other"
COPY = "web-app-cst-mywork"
LEFT = "left in place, the pull did not place it"


class _PullFixture:
    """Mixin with a core roles/, a role repository and a pull helper.

    Combined with ``unittest.TestCase`` on each concrete class so the
    test-discovery lint sees the ``TestCase`` base directly.
    """

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roles = roles_dir(self.root, "web-app-nextcloud")
        self.work = self.root / "build" / "custom-roles"
        self.repo = role_repo(self.root)
        self.inventories = 0

    def next_inventory(self) -> Path:
        self.inventories += 1
        return self.root / f"inventory-{self.inventories}"

    def pull(self, applications: dict, groups: tuple[str, ...] = (ROLE,)) -> list[str]:
        inv = inventory(self.next_inventory(), list(groups), applications)
        return pull(inv, self.roles, self.work)

    def pull_yaml(self, devices: str, host_vars: str) -> list[str]:
        base = self.next_inventory()
        write(base / "host_vars/localhost.yml", host_vars)
        return pull(write(base / "devices.yml", devices), self.roles, self.work)

    def placed(self) -> list[str]:
        return sorted(path.name for path in self.roles.iterdir())

    def leftovers(self) -> list[Path]:
        if not self.work.exists():
            return []
        return [path for path in self.work.iterdir() if path.is_dir()]

    def tag(self, name: str) -> None:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "tag", name)


class TestPullPlacement(_PullFixture, unittest.TestCase):
    def test_role_is_placed_at_its_tag_with_the_resolved_commit(self):
        lines = self.pull({ROLE: declaration(str(self.repo))})
        self.assertEqual(
            "release: v1\n", read_text(str(self.roles / ROLE / ROLE_FILE_TASKS_MAIN))
        )
        self.assertTrue(is_placed(self.roles / ROLE))
        self.assertRegex(
            lines[0], rf"^{ROLE}: .* @ v1\.0\.0 \(commit [0-9a-f]{{40}}\)$"
        )

    def test_placed_role_carries_no_git_metadata(self):
        self.pull({ROLE: declaration(str(self.repo), path=ROLE_PATH)})
        self.assertFalse((self.roles / ROLE / ".git").exists())

    def test_local_working_tree_is_placed_without_a_version(self):
        write(self.repo / ROLE_PATH / ROLE_FILE_TASKS_MAIN, "release: uncommitted\n")
        self.pull({ROLE: declaration(str(self.repo), version=None)})
        self.assertEqual(
            "release: uncommitted\n",
            read_text(str(self.roles / ROLE / ROLE_FILE_TASKS_MAIN)),
        )

    def test_pull_again_replaces_the_placed_content(self):
        self.pull({ROLE: declaration(str(self.repo))})
        write(self.roles / ROLE / "stale.yml", "stale: true\n")
        self.pull({ROLE: declaration(str(self.repo))})
        self.assertFalse((self.roles / ROLE / "stale.yml").exists())
        self.assertTrue((self.roles / ROLE / ROLE_FILE_VARS_MAIN).is_file())

    def test_role_the_inventory_no_longer_declares_is_removed(self):
        self.pull({ROLE: declaration(str(self.repo))})
        lines = self.pull({}, groups=())
        self.assertEqual(["web-app-nextcloud"], self.placed())
        self.assertIn(f"{ROLE}: removed, the inventory no longer declares it", lines)

    def test_in_tree_roles_are_never_touched(self):
        self.pull({ROLE: declaration(str(self.repo))})
        self.assertEqual([ROLE, "web-app-nextcloud"], self.placed())

    def test_no_staging_or_leftover_directory_remains(self):
        self.pull({ROLE: declaration(str(self.repo))})
        self.pull({ROLE: declaration(str(self.repo))})
        self.assertEqual([ROLE, "web-app-nextcloud"], self.placed())
        self.assertEqual([], self.leftovers())

    def test_undeclared_directory_the_pull_did_not_place_is_left_alone(self):
        write(self.roles / OTHER / "keep.yml", "keep: true\n")
        lines = self.pull({ROLE: declaration(str(self.repo))})
        self.assertTrue((self.roles / OTHER / "keep.yml").is_file())
        self.assertIn(f"{OTHER}: {LEFT}", lines)


class TestPullRefusal(_PullFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.pull({ROLE: declaration(str(self.repo))})
        write(self.roles / ROLE / "sentinel.yml", "placed: true\n")

    def assert_untouched(self) -> None:
        self.assertTrue((self.roles / ROLE / "sentinel.yml").is_file())
        self.assertEqual([ROLE, "web-app-nextcloud"], self.placed())
        self.assertEqual([], self.leftovers())

    def test_branch_as_version_is_refused_before_anything_changes(self):
        with self.assertRaisesRegex(CustomRoleError, "'feature' names a branch"):
            self.pull({ROLE: declaration(str(self.repo), version="feature")})
        self.assert_untouched()

    def test_application_id_other_than_the_group_names_both(self):
        other = role_repo(self.root / "other", application_id="web-app-demo")
        with self.assertRaisesRegex(
            CustomRoleError,
            f"application_id is 'web-app-demo', but the group is '{ROLE}'",
        ):
            self.pull({ROLE: declaration(str(other))})
        self.assert_untouched()

    def test_missing_application_id_is_refused(self):
        write(self.repo / ROLE_PATH / ROLE_FILE_VARS_MAIN, "other: value\n")
        with self.assertRaisesRegex(CustomRoleError, "application_id is None"):
            self.pull({ROLE: declaration(str(self.repo), version=None)})
        self.assert_untouched()

    def test_source_without_meta_main_is_refused(self):
        (self.repo / ROLE_PATH / ROLE_FILE_META_MAIN).unlink()
        with self.assertRaisesRegex(CustomRoleError, "no role directory"):
            self.pull({ROLE: declaration(str(self.repo), version=None)})
        self.assert_untouched()

    def test_invalid_declaration_is_refused_before_anything_changes(self):
        with self.assertRaisesRegex(CustomRoleError, "source.path is missing"):
            self.pull(
                {
                    ROLE: {
                        "custom": True,
                        "source": {"url": str(self.repo), "version": "v1.0.0"},
                    }
                }
            )
        self.assert_untouched()

    def test_path_that_is_no_directory_in_the_source_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "source.path is not a directory"):
            self.pull({ROLE: declaration(str(self.repo), path=f"absent/{ROLE}")})
        self.assert_untouched()

    def test_local_source_inside_its_placement_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "never deletes its own source"):
            self.pull(
                {ROLE: declaration(str(self.root), version=None, path=f"roles/{ROLE}")}
            )
        self.assert_untouched()

    def test_a_failing_role_leaves_every_placed_role_unchanged(self):
        broken = {
            "custom": True,
            "source": {"url": str(self.root / "absent"), "path": f"x/{OTHER}"},
        }
        with self.assertRaisesRegex(CustomRoleError, OTHER):
            self.pull(
                {ROLE: declaration(str(self.repo)), OTHER: broken}, groups=(ROLE, OTHER)
            )
        self.assert_untouched()

    def test_missing_inventory_is_refused(self):
        with self.assertRaisesRegex(CustomRoleError, "neither a file nor a directory"):
            pull(self.root / "absent/devices.yml", self.roles, self.work)
        self.assert_untouched()

    def test_unparsable_vars_file_stops_the_pull_naming_it(self):
        inv = inventory(self.next_inventory(), [], {})
        broken = write(inv.parent / "group_vars/all.yml", "applications:\n  x: [open\n")
        with self.assertRaisesRegex(
            CustomRoleError, rf"{re.escape(str(broken))}: cannot read"
        ):
            pull(inv, self.roles, self.work)
        self.assert_untouched()

    def test_vars_file_that_is_no_utf8_stops_the_pull_naming_it(self):
        inv = inventory(self.next_inventory(), [], {})
        latin = inv.parent / "group_vars/all.yml"
        latin.parent.mkdir()
        latin.write_bytes("applications: {caf\xe9: {}}\n".encode("latin-1"))
        with self.assertRaisesRegex(
            CustomRoleError, rf"{re.escape(str(latin))}: cannot read"
        ):
            pull(inv, self.roles, self.work)
        self.assert_untouched()

    def test_inventory_file_that_is_no_utf8_stops_the_pull_naming_it(self):
        inv = inventory(self.next_inventory(), [], {})
        inv.write_bytes("all:\n  hosts:\n    caf\xe9: {}\n".encode("latin-1"))
        with self.assertRaisesRegex(
            CustomRoleError, rf"{re.escape(str(inv))}: cannot read"
        ):
            pull(inv, self.roles, self.work)
        self.assert_untouched()


class TestPullInventoryForms(_PullFixture, unittest.TestCase):
    def test_directory_inventory_is_read_like_a_file_inventory(self):
        inv = inventory(
            self.next_inventory(), [ROLE], {ROLE: declaration(str(self.repo))}
        )
        pull(inv.parent, self.roles, self.work)
        self.assertTrue(is_placed(self.roles / ROLE))

    def test_group_of_a_hosts_file_in_a_directory_inventory_needs_custom_true(self):
        base = self.next_inventory()
        write(base / "hosts", f"[{ROLE}]\nlocalhost\n")
        write(base / "README.md", "[web-app-cst-ignored]\n")
        write(base / "host_vars/localhost.yml", "applications: {}\n")
        with self.assertRaises(CustomRoleError) as refused:
            pull(base, self.roles, self.work)
        self.assertIn(f"{ROLE}: inventory group without", str(refused.exception))
        self.assertNotIn("web-app-cst-ignored", str(refused.exception))

    def test_host_list_declares_nothing_and_changes_nothing(self):
        self.pull({ROLE: declaration(str(self.repo))})
        self.assertEqual([], pull(Path("localhost,"), self.roles, self.work))
        self.assertTrue(is_placed(self.roles / ROLE))


class TestPullAnsibleTags(_PullFixture, unittest.TestCase):
    DEVICES = (
        "all:\n"
        "  hosts:\n"
        "    localhost:\n"
        "      motd: !unsafe '{{ literal }}'\n"
        "  children:\n"
        f"    {ROLE}:\n"
        "      hosts:\n"
        "        localhost: {}\n"
    )

    def host_vars(self, url: str) -> str:
        return (
            "secret: !vault |\n"
            "  $ANSIBLE_VAULT;1.1;AES256\n"
            "  6162\n"
            "applications:\n"
            f"  {ROLE}:\n"
            "    custom: true\n"
            "    source:\n"
            f"      url: {url}\n"
            "      version: v1.0.0\n"
            f"      path: {ROLE_PATH}\n"
        )

    def test_tagged_values_elsewhere_in_the_inventory_keep_the_pull_working(self):
        self.pull_yaml(self.DEVICES, self.host_vars(str(self.repo)))
        self.assertTrue(is_placed(self.roles / ROLE))

    def test_tagged_source_value_is_refused_like_a_jinja_value(self):
        with self.assertRaisesRegex(
            CustomRoleError,
            f"{ROLE}: applications.{ROLE}.source.url holds a !unsafe value",
        ):
            self.pull_yaml(self.DEVICES, self.host_vars(f"!unsafe '{self.repo}'"))
        self.assertEqual(["web-app-nextcloud"], self.placed())


class TestPullOwnership(_PullFixture, unittest.TestCase):
    def test_symbolic_link_under_a_declared_name_is_refused_and_kept(self):
        target = self.root / "elsewhere"
        write(target / "keep.yml", "keep: true\n")
        (self.roles / ROLE).symlink_to(target)
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: .* is a symbolic link .* remove the link"
        ):
            self.pull({ROLE: declaration(str(self.repo))})
        self.assertTrue((self.roles / ROLE).is_symlink())
        self.assertTrue((target / "keep.yml").is_file())

    def test_hand_placed_directory_under_a_declared_name_is_refused_and_kept(self):
        write(self.roles / ROLE / "mine.yml", "mine: true\n")
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: .* was not placed by a pull"
        ):
            self.pull({ROLE: declaration(str(self.repo))})
        self.assertTrue((self.roles / ROLE / "mine.yml").is_file())
        self.assertFalse((self.roles / ROLE / MARKER_FILE).exists())

    def test_copy_of_a_placed_role_is_left_in_place_and_reported(self):
        self.pull({ROLE: declaration(str(self.repo))})
        shutil.copytree(self.roles / ROLE, self.roles / COPY)
        lines = self.pull({}, groups=())
        self.assertEqual([COPY, "web-app-nextcloud"], self.placed())
        self.assertIn(f"{COPY}: {LEFT}", lines)

    def test_declared_name_that_meets_a_copy_is_refused_and_kept(self):
        self.pull({ROLE: declaration(str(self.repo))})
        shutil.copytree(self.roles / ROLE, self.roles / COPY)
        write(self.roles / COPY / "mine.yml", "mine: true\n")
        checkout = local_role(self.root, COPY)
        mine = declaration(str(checkout), version=None, path=f"ansible/roles/{COPY}")
        with self.assertRaisesRegex(
            CustomRoleError, f"{COPY}: .* was not placed by a pull"
        ):
            self.pull({ROLE: declaration(str(self.repo)), COPY: mine}, (ROLE, COPY))
        self.assertTrue((self.roles / COPY / "mine.yml").is_file())


class TestPullMarker(_PullFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.in_tree = write(
            self.roles / "web-app-nextcloud" / ROLE_FILE_TASKS_MAIN, "in-tree: true\n"
        )

    def assert_in_tree_untouched(self) -> None:
        text = self.in_tree.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual("in-tree: true\n", text)
        self.assertEqual(["web-app-nextcloud"], self.placed())
        self.assertEqual([], self.leftovers())

    def test_marker_link_in_a_local_source_is_refused_and_never_followed(self):
        checkout = local_role(self.root, ROLE)
        (checkout / "ansible/roles" / ROLE / MARKER_FILE).symlink_to(self.in_tree)
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: .*{MARKER_FILE} is a symbolic link"
        ):
            self.pull(
                {
                    ROLE: declaration(
                        str(checkout), version=None, path=f"ansible/roles/{ROLE}"
                    )
                }
            )
        self.assert_in_tree_untouched()

    def test_relative_marker_link_in_a_tag_is_refused(self):
        (self.repo / ROLE_PATH / MARKER_FILE).symlink_to(ROLE_FILE_TASKS_MAIN)
        self.tag("v2.0.0")
        with self.assertRaisesRegex(
            CustomRoleError, f"{ROLE}: .*{MARKER_FILE} is a symbolic link"
        ):
            self.pull({ROLE: declaration(str(self.repo), version="v2.0.0")})
        self.assert_in_tree_untouched()

    def test_absolute_link_in_a_tag_is_refused_naming_the_group(self):
        (self.repo / ROLE_PATH / MARKER_FILE).symlink_to(self.in_tree)
        self.tag("v2.0.0")
        with self.assertRaisesRegex(CustomRoleError, f"^{ROLE}: .*absolute"):
            self.pull({ROLE: declaration(str(self.repo), version="v2.0.0")})
        self.assert_in_tree_untouched()


class TestPullCommit(_PullFixture, unittest.TestCase):
    def test_interrupt_while_deleting_the_old_copy_keeps_the_new_one(self):
        self.pull({ROLE: declaration(str(self.repo))})
        write(self.roles / ROLE / "stale.yml", "stale: true\n")
        rmtree = shutil.rmtree

        def interrupted(path, *args, **kwargs):
            if ".retired." in str(path):
                raise KeyboardInterrupt
            return rmtree(path, *args, **kwargs)

        with (
            mock.patch.object(placement.shutil, "rmtree", interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.pull({ROLE: declaration(str(self.repo))})
        self.assertTrue(is_placed(self.roles / ROLE))
        self.assertFalse((self.roles / ROLE / "stale.yml").exists())
        self.pull({ROLE: declaration(str(self.repo))})
        self.assertEqual([], self.leftovers())

    def test_directory_that_appears_at_a_declared_name_during_the_pull_is_kept(self):
        stage = placement.stage

        def stage_beside_a_hand_placed_copy(group, source, target):
            write(self.roles / group / "mine.yml", "mine: true\n")
            return stage(group, source, target)

        with (
            mock.patch.object(placement, "stage", stage_beside_a_hand_placed_copy),
            self.assertRaisesRegex(
                CustomRoleError, f"{ROLE}: .* was not placed by a pull"
            ),
        ):
            self.pull({ROLE: declaration(str(self.repo))})
        self.assertTrue((self.roles / ROLE / "mine.yml").is_file())
        self.assertFalse(is_placed(self.roles / ROLE))
        self.assertEqual([], self.leftovers())

    def test_clean_waits_until_a_running_pull_has_finished(self):
        events: list[tuple[str, object]] = []
        cleaner = threading.Thread(
            target=lambda: events.append(("cleaned", clean(self.roles, self.work)))
        )
        stage = placement.stage

        def stage_while_a_clean_starts(group, source, target):
            cleaner.start()
            cleaner.join(timeout=0.5)
            events.append(("clean still waiting", cleaner.is_alive()))
            return stage(group, source, target)

        with mock.patch.object(placement, "stage", stage_while_a_clean_starts):
            self.pull({ROLE: declaration(str(self.repo))})
        cleaner.join(timeout=30)
        self.assertEqual(("clean still waiting", True), events[0])
        self.assertEqual("cleaned", events[1][0])
        self.assertEqual(["web-app-nextcloud"], self.placed())


class TestClean(_PullFixture, unittest.TestCase):
    def test_removes_only_the_roles_the_pull_placed_and_reports_the_rest(self):
        checkout = local_role(self.root, OTHER)
        self.pull(
            {
                ROLE: declaration(str(self.repo)),
                OTHER: declaration(
                    str(checkout), version=None, path=f"ansible/roles/{OTHER}"
                ),
            },
            groups=(ROLE, OTHER),
        )
        shutil.copytree(self.roles / ROLE, self.roles / COPY)
        write(self.roles / "web-app-cst-hand" / "mine.yml", "mine: true\n")
        target = self.root / "elsewhere"
        write(target / "keep.yml", "keep: true\n")
        (self.roles / "web-app-cst-link").symlink_to(target)
        lines = clean(self.roles, self.work)
        self.assertEqual(
            [
                f"{ROLE}: removed",
                f"web-app-cst-hand: {LEFT}",
                f"web-app-cst-link: {LEFT}",
                f"{COPY}: {LEFT}",
                f"{OTHER}: removed",
            ],
            lines,
        )
        self.assertEqual(
            ["web-app-cst-hand", "web-app-cst-link", COPY, "web-app-nextcloud"],
            self.placed(),
        )
        self.assertTrue((target / "keep.yml").is_file())
        self.assertEqual([], self.leftovers())


if __name__ == "__main__":
    unittest.main()
