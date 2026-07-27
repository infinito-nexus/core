import unittest
from unittest import mock

from ansible.errors import AnsibleActionFail

from plugins.action.package_install import ActionModule
from utils.packages.plan import ModuleCall


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


class TestBecomeIsRestored(unittest.TestCase):
    def _action(self):
        action = _action({})
        action._play_context = mock.Mock(become=False, become_user="root")
        action._execute_module = mock.Mock(return_value={"changed": True})
        return action

    def test_become_user_is_set_for_the_call(self):
        action = self._action()
        seen = {}
        action._execute_module.side_effect = lambda **_kw: (
            seen.update(
                become=action._play_context.become,
                become_user=action._play_context.become_user,
            )
            or {"changed": True}
        )
        action._execute(ModuleCall("m", {}, become_user="aur_builder"), {})
        self.assertEqual(seen, {"become": True, "become_user": "aur_builder"})

    def test_become_is_restored_after_the_call(self):
        action = self._action()
        action._execute(ModuleCall("m", {}, become_user="aur_builder"), {})
        self.assertFalse(action._play_context.become)
        self.assertEqual(action._play_context.become_user, "root")

    def test_become_is_restored_after_a_failing_call(self):
        action = self._action()
        action._execute_module.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            action._execute(ModuleCall("m", {}, become_user="aur_builder"), {})
        self.assertFalse(action._play_context.become)
        self.assertEqual(action._play_context.become_user, "root")

    def test_a_call_without_become_user_leaves_the_context_alone(self):
        action = self._action()
        action._execute(ModuleCall("m", {}), {})
        self.assertFalse(action._play_context.become)


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
