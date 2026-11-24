import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

CORE = PROJECT_ROOT / "roles/svc-db-openldap/tasks/00_core.yml"
LABEL_ADD = "container node update --label-add {{ LDAP.SERVER.NODE_LABEL }}=true"
NODE = "ldap-01.cluster.example.org"
FACTS = {"hostname": "ldap-01", "fqdn": NODE}


def _tasks():
    return load_yaml_any(str(CORE), default_if_missing=[])


def _labelled_node(command):
    """
    Args:
        command: the label task's command.

    Returns:
        The node the command labels on a host whose inventory name, which
        sys-hostname makes its kernel hostname and so its swarm node name, is
        an FQDN.
    """
    templar = Templar(
        loader=DataLoader(),
        variables={
            "inventory_hostname": NODE,
            "ansible_facts": FACTS,
            "LDAP": {"SERVER": {"NODE_LABEL": "ldap"}},
        },
    )
    return templar.template(_trust_as_template(command)).split()[-1]


def _is_label(task):
    return LABEL_ADD in str(task.get("ansible.builtin.command", ""))


def _index(tasks, predicate):
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _runs(task, swarm):
    """
    Args:
        task: a task of the role.
        swarm: the value IS_SWARM_MODE renders to.

    Returns:
        Whether the task's ``when`` holds.
    """
    templar = Templar(loader=DataLoader(), variables={"IS_SWARM_MODE": swarm})
    condition = "{{ (" + task["when"] + ") | bool }}"
    return templar.template(_trust_as_template(condition))


class TestSocketNodeLabel(unittest.TestCase):
    def setUp(self):
        self.tasks = _tasks()
        self.label = self.tasks[_index(self.tasks, _is_label)]

    def test_every_host_labels_its_own_node_through_the_manager(self):
        self.assertEqual(_labelled_node(self.label["ansible.builtin.command"]), NODE)
        self.assertEqual(self.label["delegate_to"], "{{ STACK_HOST }}")
        self.assertNotIn("run_once", self.label)

    def test_negative_control_the_short_kernel_name_misses_an_fqdn_node(self):
        short = self.label["ansible.builtin.command"].replace(
            "{{ inventory_hostname }}", "{{ ansible_facts['hostname'] }}"
        )
        self.assertNotEqual(short, self.label["ansible.builtin.command"])
        self.assertNotEqual(_labelled_node(short), NODE)

    def test_a_swarm_deploy_labels_the_node(self):
        self.assertTrue(_runs(self.label, True))

    def test_negative_control_a_compose_deploy_writes_no_label(self):
        self.assertFalse(_runs(self.label, False))

    def test_the_node_is_labelled_before_the_stack_starts(self):
        docker = _index(
            self.tasks, lambda task: task.get("include_tasks") == "01_docker.yml"
        )
        self.assertLess(_index(self.tasks, _is_label), docker)


if __name__ == "__main__":
    unittest.main()
