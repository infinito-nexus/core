import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/web-app-moodle/tasks"
ENTRY = "01_manager_ops.yml"
LDAP_SYNC = "--execute='\\auth_ldap\\task\\sync_task'"
OIDC_HANDOVER = "SET auth = 'oidc'"
OIDC_GATE = "MOODLE_OIDC_ENABLED | bool"


def run_order(name, gates=()):
    """
    Args:
        name: task file relative to roles/web-app-moodle/tasks
        gates: when conditions of the includes that led to this file

    Returns:
        (shell, gates) per task in run order, every include_tasks of a literal role-local file expanded in place
    """
    steps = []
    for task in load_yaml_any(str(TASKS / name)):
        when = task.get("when")
        own = gates + ((when,) if isinstance(when, str) else tuple(when or ()))
        include = str(task.get("include_tasks", ""))
        if include and "{{" not in include and (TASKS / include).is_file():
            steps.extend(run_order(include, own))
            continue
        shell = task.get("shell", task.get("ansible.builtin.shell", ""))
        steps.append((str(shell), own))
    return steps


class TestOidcHandoverFollowsLdapSync(unittest.TestCase):
    def setUp(self):
        self.steps = run_order(ENTRY)
        self.handovers = [
            index
            for index, (shell, _) in enumerate(self.steps)
            if OIDC_HANDOVER in shell
        ]
        self.syncs = [
            index for index, (shell, _) in enumerate(self.steps) if LDAP_SYNC in shell
        ]

    def test_one_task_hands_the_accounts_to_auth_oidc_and_only_under_sso(self):
        self.assertEqual(len(self.handovers), 1, self.handovers)
        self.assertEqual(
            self.steps[self.handovers[0]][1],
            (OIDC_GATE,),
            "the handover must run under sso alone; an ldap gate on it skips variant 1",
        )

    def test_accounts_the_ldap_sync_creates_reach_auth_oidc_in_the_same_deploy(self):
        self.assertTrue(self.syncs, "the deploy no longer runs the auth_ldap sync")
        self.assertGreater(
            self.handovers[0],
            self.syncs[-1],
            "auth_ldap creates the accounts it pre-provisions with auth ldap; a handover to "
            "auth_oidc that runs before the sync leaves them on ldap, and their OIDC login "
            "fails in authenticate_user_login and loops back to Keycloak",
        )


if __name__ == "__main__":
    unittest.main()
