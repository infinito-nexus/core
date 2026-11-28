import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from plugins.filter.resource_filter import resource_filter
from utils.cache.applications import get_merged_applications
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.tests.caches import fresh_caches

APPLICATION_ID = "web-app-nextcloud"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
TASKS = ROLE / "tasks" / "utils" / "ldap_refresh.yml"
LABEL = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "12_ldap.yml"))["LDAP"][
    "SERVER"
]["NODE_LABEL"]
RBAC_SYNC_VARS = load_yaml_any(
    str(PROJECT_ROOT / "roles" / "sys-ctl-mtn-rbac-sync" / ROLE_FILE_VARS_MAIN)
)
CRON = VARS["NEXTCLOUD_CRON_SERVICE"]
APP = entity_name(APPLICATION_ID)
DIRECTORY = "svc-db-openldap"
STACK_HOST = "mgr-01"
WITH_DIRECTORY = [APPLICATION_ID, DIRECTORY]
WITHOUT_DIRECTORY = [APPLICATION_ID]
USER_LDAP_OFF = {APPLICATION_ID: {"addons": {"user_ldap": {"enabled": False}}}}


def merged(deployed, directory_hosts, overrides=None):
    """
    Args:
        deployed: the inventory groups of the stack host, which renders the stack.
        directory_hosts: the hosts of the cluster in ``svc-db-openldap``.
        overrides: inventory ``applications`` overrides, none by default.

    Returns:
        The rendered applications payload.
    """
    variables = {
        "group_names": deployed,
        "groups": {DIRECTORY: directory_hosts},
        "applications": overrides or {},
        "LDAP": {"SERVER": {"NODE_LABEL": LABEL}},
    }
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    with fresh_caches(files_changed=False):
        return get_merged_applications(variables=variables, templar=templar)


def node_label(applications, service):
    """
    Args:
        applications: the rendered applications payload.
        service: a service key of the role.

    Returns:
        The node label ``deploy.yml.j2`` pins the service to, empty for none.
    """
    return resource_filter(applications, APPLICATION_ID, "node_label", service, "")


def pinned_single_task(applications, service):
    """
    Args:
        applications: the rendered applications payload.
        service: a service key of the role.

    Returns:
        Whether the service runs exactly one task, which swarm numbers slot 1,
        on a node that holds the ldapi socket, the node the RBAC timer runs on.
    """
    entry = applications[APPLICATION_ID]["services"][service]
    return entry.get("replicas") == 1 and node_label(applications, service) == LABEL


def hook_service(include):
    """
    Args:
        include: the vars ``tasks/utils/ldap_refresh.yml`` hands the RBAC sync util.

    Returns:
        The service key the refresh hook acts on.
    """
    templar = Templar(
        loader=DataLoader(),
        variables={"NEXTCLOUD_CRON_SERVICE": CRON, "NEXTCLOUD_SERVICE": APP},
    )
    return templar.template(trust_as_template(include["rbac_sync_service_key"]))


class TestCronRunsTheRefreshNextToTheDirectory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.with_directory = merged(WITH_DIRECTORY, [STACK_HOST])
        cls.include = load_yaml_any(str(TASKS))[0]["vars"]

    def test_cron_runs_next_to_the_directory_while_user_ldap_is_on(self):
        self.assertEqual(node_label(self.with_directory, CRON), LABEL)

    def test_the_app_and_its_other_workers_stay_unconstrained(self):
        for service in (APP, VARS["NEXTCLOUD_TASKPROCESSING_SERVICE"]):
            with self.subTest(service=service):
                self.assertEqual(node_label(self.with_directory, service), "")

    def test_negative_control_no_directory_in_the_inventory_means_no_label(self):
        self.assertEqual(node_label(merged(WITHOUT_DIRECTORY, []), CRON), "")

    def test_a_stack_host_outside_the_directory_runs_neither_user_ldap_nor_the_timer(
        self,
    ):
        outside = merged(WITHOUT_DIRECTORY, ["mgr-02"])
        self.assertIs(outside[APPLICATION_ID]["addons"]["user_ldap"]["enabled"], False)
        self.assertEqual(node_label(outside, CRON), "")
        self.assertEqual(
            RBAC_SYNC_VARS["RBAC_SYNC_LDAP_ENABLED"],
            "{{ STACK_HOST in (groups['svc-db-openldap'] | default([])) }}",
        )

    def test_negative_control_with_user_ldap_off_cron_is_unconstrained(self):
        self.assertEqual(
            node_label(merged(WITH_DIRECTORY, [STACK_HOST], USER_LDAP_OFF), CRON), ""
        )

    def test_the_hook_acts_through_the_cron_container(self):
        self.assertEqual(hook_service(self.include), CRON)
        self.assertEqual(
            self.include["rbac_sync_container"], "{{ NEXTCLOUD_CRON_CONTAINER }}"
        )

    def test_the_timer_finds_the_hook_as_task_slot_one_on_the_directory_node(self):
        self.assertTrue(
            pinned_single_task(self.with_directory, hook_service(self.include))
        )

    def test_negative_control_the_app_service_is_no_reachable_target(self):
        app_target = {
            **self.include,
            "rbac_sync_service_key": "{{ NEXTCLOUD_SERVICE }}",
        }
        self.assertFalse(
            pinned_single_task(self.with_directory, hook_service(app_target))
        )


if __name__ == "__main__":
    unittest.main()
