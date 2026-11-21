import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/svc-db-openldap"
LAYOUT = load_yaml_any(str(ROLE_DIR / "tasks/06_mailbox.yml"))
CORE = load_yaml_any(str(ROLE_DIR / "tasks/00_core.yml"))
RBAC_SYNC_VARS = load_yaml_any(
    str(PROJECT_ROOT / "roles/sys-ctl-mtn-rbac-sync" / ROLE_FILE_VARS_MAIN)
)
SEED_TASKS = "mailbox.yml"


def _index(tasks, needle):
    return next(
        index
        for index, task in enumerate(tasks)
        if needle in str(task.get("ldap_entries", {}).get("entries", ""))
    )


def _seed_includes(tasks):
    return [
        task
        for task in tasks
        if task.get("ansible.builtin.include_role", {}).get("tasks_from") == SEED_TASKS
    ]


class TestMailboxLayoutTasks(unittest.TestCase):
    def test_the_layout_reads_the_current_address(self):
        attrs = LAYOUT[0]["community.general.ldap_search"]["attrs"]
        self.assertIn("{{ LDAP.USER.ATTRIBUTES.MAIL }}", attrs)

    def test_the_current_external_address_is_kept_before_the_mailbox_replaces_it(self):
        keep = _index(LAYOUT, "openldap_current_mail_secondary_entries")
        rewrite = _index(LAYOUT, "openldap_mailbox_entries")
        self.assertLess(keep, rewrite)
        self.assertEqual(LAYOUT[keep]["ldap_entries"]["state"], "missing")
        self.assertEqual(LAYOUT[rewrite]["ldap_entries"]["state"], "exact")

    def test_the_timer_seed_starts_only_after_the_layout_is_applied(self):
        seeds = _seed_includes(LAYOUT)
        self.assertEqual(len(seeds), 1)
        self.assertIs(seeds[0]["vars"]["rbac_sync_mailbox_enabled"], True)
        self.assertGreater(
            LAYOUT.index(seeds[0]), _index(LAYOUT, "openldap_mailbox_entries")
        )

    def test_the_directory_role_itself_only_ever_stops_the_seed(self):
        self.assertEqual(
            [
                task["vars"]["rbac_sync_mailbox_enabled"]
                for task in _seed_includes(CORE)
            ],
            [False],
        )

    def test_the_timer_configuration_carries_no_mailbox_seed(self):
        self.assertNotIn("mailbox", RBAC_SYNC_VARS["RBAC_SYNC_CONFIG"])


if __name__ == "__main__":
    unittest.main()
