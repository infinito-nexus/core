import unittest
from unittest import mock

from ansible.errors import AnsibleActionFail
from ansible.plugins.loader import become_loader, shell_loader

from plugins.action.package_install import ActionModule
from utils.packages.plan import GENERIC_PACKAGE, ModuleCall


def _action(args) -> ActionModule:
    action = ActionModule.__new__(ActionModule)
    action._task = mock.Mock(args=args)
    return action


class TestPackageIds(unittest.TestCase):
    def test_single_id(self):
        self.assertEqual(_action({"id": "git"})._package_ids(), ["git"])

    def test_list_of_ids(self):
        self.assertEqual(
            _action({"id": ["git", "curl"]})._package_ids(), ["git", "curl"]
        )

    def test_whitespace_is_trimmed_and_blanks_dropped(self):
        self.assertEqual(_action({"id": [" git ", "", "  "]})._package_ids(), ["git"])

    def test_missing_id_fails(self):
        with self.assertRaises(AnsibleActionFail):
            _action({})._package_ids()

    def test_empty_list_fails(self):
        with self.assertRaises(AnsibleActionFail):
            _action({"id": []})._package_ids()


class TestState(unittest.TestCase):
    def test_defaults_to_present(self):
        self.assertEqual(_action({"id": "git"})._state(), "present")

    def test_absent_is_accepted(self):
        self.assertEqual(_action({"id": "git", "state": "absent"})._state(), "absent")

    def test_unknown_state_fails(self):
        with self.assertRaises(AnsibleActionFail):
            _action({"id": "git", "state": "latest"})._state()


class TestOwningRole(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "nfs-ganesha": mock.Mock(role="svc-storage-nfs-server", shared=False),
            "git": mock.Mock(role=None, shared=True),
        }

    def _spec_for(self, package_id, role):
        return _action({"id": package_id})._spec_for(
            self.registry, package_id, "debian", "Debian", role
        )

    def test_foreign_role_id_fails(self):
        with self.assertRaises(AnsibleActionFail) as caught:
            self._spec_for("nfs-ganesha", "desk-micro")
        self.assertIn("svc-storage-nfs-server", str(caught.exception))

    def test_unknown_id_fails(self):
        with self.assertRaises(AnsibleActionFail):
            self._spec_for("nope", "desk-micro")

    def test_own_id_resolves(self):
        with mock.patch(
            "plugins.action.package_install.resolve", return_value="spec"
        ) as resolver:
            spec = self._spec_for("nfs-ganesha", "svc-storage-nfs-server")
        self.assertEqual(spec, "spec")
        resolver.assert_called_once()

    def test_shared_id_resolves_for_any_role(self):
        with mock.patch("plugins.action.package_install.resolve", return_value="spec"):
            spec = self._spec_for("git", "desk-micro")
        self.assertEqual(spec, "spec")

    def test_no_role_context_skips_the_check(self):
        with mock.patch("plugins.action.package_install.resolve", return_value="spec"):
            spec = self._spec_for("nfs-ganesha", None)
        self.assertEqual(spec, "spec")


class TestModuleName(unittest.TestCase):
    def _module_name(self, module, facts):
        return _action({})._module_name(ModuleCall(module, {}), facts)

    def test_generic_package_becomes_the_hosts_package_manager(self):
        self.assertEqual(
            self._module_name(GENERIC_PACKAGE, {"pkg_mgr": "pacman"}), "pacman"
        )

    def test_concrete_modules_pass_through(self):
        self.assertEqual(
            self._module_name("community.general.copr", {"pkg_mgr": "dnf"}),
            "community.general.copr",
        )

    def test_missing_pkg_mgr_fails(self):
        with self.assertRaises(AnsibleActionFail):
            self._module_name(GENERIC_PACKAGE, {})


class TestBecomeEscalation(unittest.TestCase):
    def setUp(self):
        self.become = become_loader.get("sudo")
        self.become.set_options(direct={"become_user": "root"})
        self.shell = shell_loader.get("sh")
        self.commands = []

    def _action(self, become):
        action = _action({})
        action._connection = mock.Mock(become=become, transport="local")
        action._execute_module = mock.Mock(side_effect=self._record)
        return action

    def _record(self, **_kwargs):
        self.commands.append(self.become.build_become_command("MODULE", self.shell))
        return {"changed": True}

    def test_the_build_user_call_is_wrapped(self):
        action = self._action(self.become)
        action._execute(ModuleCall("m", {}, become_user="aur_builder"), {}, {})
        self.assertIn("-u aur_builder", self.commands[0])

    def test_a_plain_call_is_not_wrapped(self):
        action = self._action(self.become)
        action._execute(ModuleCall("m", {}), {}, {})
        self.assertNotIn("-u aur_builder", self.commands[0])
        self.assertIn("-u root", self.commands[0])

    def test_the_become_user_is_restored(self):
        action = self._action(self.become)
        action._execute(ModuleCall("m", {}, become_user="aur_builder"), {}, {})
        self.assertEqual(self.become.get_option("become_user"), "root")

    def test_a_later_call_on_the_same_connection_is_unaffected(self):
        action = self._action(self.become)
        action._execute(ModuleCall("m", {}, become_user="aur_builder"), {}, {})
        action._execute(ModuleCall("m", {}), {}, {})
        self.assertIn("-u aur_builder", self.commands[0])
        self.assertIn("-u root", self.commands[1])
        self.assertNotIn("-u aur_builder", self.commands[1])

    def test_the_become_user_is_restored_after_a_failing_call(self):
        action = self._action(self.become)
        action._execute_module.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            action._execute(ModuleCall("m", {}, become_user="aur_builder"), {}, {})
        self.assertEqual(self.become.get_option("become_user"), "root")

    def test_without_a_become_plugin_it_fails_loud(self):
        action = self._action(None)
        with self.assertRaises(AnsibleActionFail) as caught:
            action._execute(ModuleCall("m", {}, become_user="aur_builder"), {}, {})
        self.assertIn("aur_builder", str(caught.exception))


class TestTargetFacts(unittest.TestCase):
    """A delegated install must resolve against the delegation target.

    task_vars carries the inventory host's facts even under delegate_to, so a
    RedHat node delegating to a Debian controller used to resolve dnf and then
    run it where only apt exists.
    """

    def _action(self, delegate_to, setup_result=None):
        action = _action({"id": "nfs-client"})
        action._task.delegate_to = delegate_to
        action._execute_module = mock.Mock(return_value=setup_result or {})
        return action

    def test_without_delegation_the_inventory_facts_are_used(self):
        action = self._action(None)
        facts = action._target_facts({"ansible_facts": {"pkg_mgr": "apt"}})
        self.assertEqual(facts, {"pkg_mgr": "apt"})
        action._execute_module.assert_not_called()

    def test_delegating_to_itself_is_not_delegation(self):
        action = self._action("nfs-node")
        facts = action._target_facts(
            {"inventory_hostname": "nfs-node", "ansible_facts": {"pkg_mgr": "dnf"}}
        )
        self.assertEqual(facts, {"pkg_mgr": "dnf"})
        action._execute_module.assert_not_called()

    def test_a_delegated_task_asks_the_target(self):
        action = self._action(
            "localhost",
            {
                "ansible_facts": {
                    "ansible_pkg_mgr": "apt",
                    "ansible_os_family": "Debian",
                }
            },
        )
        facts = action._target_facts(
            {
                "inventory_hostname": "nfs-node",
                "ansible_facts": {"pkg_mgr": "dnf", "os_family": "RedHat"},
            }
        )
        self.assertEqual(
            action._module_name(ModuleCall(GENERIC_PACKAGE, {}), facts), "apt"
        )

    def test_a_failing_setup_names_the_delegation_target(self):
        action = self._action("localhost", {"failed": True, "msg": "no connection"})
        with self.assertRaises(AnsibleActionFail) as caught:
            action._target_facts({"inventory_hostname": "nfs-node"})
        self.assertIn("localhost", str(caught.exception))


class TestFactShapes(unittest.TestCase):
    def test_bare_keys_from_task_vars(self):
        distribution, os_family = _action({})._facts(
            {"distribution": "Fedora", "os_family": "RedHat"}
        )
        self.assertEqual((distribution, os_family), ("fedora", "RedHat"))

    def test_prefixed_keys_from_the_setup_module(self):
        distribution, os_family = _action({})._facts(
            {"ansible_distribution": "Ubuntu", "ansible_os_family": "Debian"}
        )
        self.assertEqual((distribution, os_family), ("ubuntu", "Debian"))

    def test_missing_facts_fail_loud(self):
        with self.assertRaises(AnsibleActionFail):
            _action({})._facts({})


class TestAggregate(unittest.TestCase):
    def test_all_skipped_reports_skip(self):
        result = _action({})._aggregate([], ["selinux-python-binding"], "debian")
        self.assertTrue(result["skipped"])
        self.assertFalse(result["changed"])

    def test_changed_is_any_changed(self):
        result = _action({})._aggregate(
            [{"changed": False}, {"changed": True}], [], "debian"
        )
        self.assertTrue(result["changed"])

    def test_failure_propagates(self):
        result = _action({})._aggregate(
            [{"changed": False}, {"failed": True, "msg": "boom"}], [], "debian"
        )
        self.assertTrue(result["failed"])
        self.assertIn("boom", result["msg"])

    def test_partial_skips_are_reported(self):
        result = _action({})._aggregate([{"changed": True}], ["libntirpc"], "debian")
        self.assertEqual(result["skipped_ids"], ["libntirpc"])


if __name__ == "__main__":
    unittest.main()
