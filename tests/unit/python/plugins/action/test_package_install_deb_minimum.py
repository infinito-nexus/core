import unittest
import unittest.mock as mock

from plugins.action.package_install import ActionModule
from utils.packages.calls import DEB_INSTALL, ModuleCall
from utils.packages.outcome import aggregate

QUERY = "ansible.builtin.command"
DEB = "/var/cache/infinito/packages/cursor_3.27.6_amd64.deb"
PINNED = "3.27.6-1792578269"
FIELDS = {"rc": 0, "stdout": f"Package: cursor\nVersion: {PINNED}\n", "stderr": ""}
MISSING = {
    "rc": 1,
    "stdout": "",
    "stderr": "dpkg-query: no packages found matching cursor",
    "failed": True,
}
REACHED = {"rc": 0, "stdout": "", "stderr": ""}
NOT_REACHED = {"rc": 1, "stdout": "", "stderr": "", "failed": True}


def _installed(version):
    return {"rc": 0, "stdout": f"{version}\tii \n", "stderr": ""}


class TestDebPinIsAMinimum(unittest.TestCase):
    def _attempt(self, installed, compared=None, fields=FIELDS):
        answers = {"dpkg-deb": fields, "dpkg-query": installed, "dpkg": compared}

        def execute(module_name, module_args, **_kwargs):
            if module_name != QUERY:
                return {"changed": True}
            return answers[module_args["argv"][0]]

        action = ActionModule.__new__(ActionModule)
        action._task = mock.Mock(args={})
        action._connection = mock.Mock(become=None, transport="local")
        action._execute_module = mock.Mock(side_effect=execute)
        result = action._attempt(
            ModuleCall(DEB_INSTALL, {"deb": DEB}), {}, {"pkg_mgr": "apt"}
        )
        return action._execute_module, result

    def _argvs(self, execute):
        return [
            call.kwargs["module_args"]["argv"]
            for call in execute.call_args_list
            if call.kwargs["module_name"] == QUERY
        ]

    def _modules(self, execute):
        return [call.kwargs["module_name"] for call in execute.call_args_list]

    def test_a_newer_installed_version_skips_the_deb(self):
        execute, result = self._attempt(_installed("3.27.22-1793067078"), REACHED)
        self.assertEqual(self._modules(execute), [QUERY, QUERY, QUERY])
        self.assertEqual(
            self._argvs(execute)[-1],
            ["dpkg", "--compare-versions", "3.27.22-1793067078", "ge", PINNED],
        )
        self.assertFalse(result["changed"])
        self.assertEqual(result["module"], DEB_INSTALL)
        self.assertIn("3.27.22-1793067078", result["msg"])
        self.assertNotIn("failed", aggregate([result], [], "debian"))

    def test_the_pinned_version_installed_skips_the_deb(self):
        execute, result = self._attempt(_installed(PINNED), REACHED)
        self.assertNotIn(DEB_INSTALL, self._modules(execute))
        self.assertFalse(result["changed"])

    def test_an_older_installed_version_installs_the_deb(self):
        execute, result = self._attempt(_installed("3.27.0-1790000000"), NOT_REACHED)
        self.assertEqual(self._modules(execute), [QUERY, QUERY, QUERY, DEB_INSTALL])
        self.assertEqual(execute.call_args.kwargs["module_args"], {"deb": DEB})
        self.assertTrue(result["changed"])

    def test_a_missing_package_installs_the_deb_without_comparing(self):
        execute, result = self._attempt(MISSING)
        self.assertEqual(self._modules(execute), [QUERY, QUERY, DEB_INSTALL])
        self.assertTrue(result["changed"])

    def test_the_queries_run_without_variable_expansion(self):
        execute, _result = self._attempt(_installed(PINNED), REACHED)
        for call in execute.call_args_list:
            self.assertFalse(call.kwargs["module_args"]["expand_argument_vars"])

    def test_an_unreadable_deb_leaves_the_decision_to_apt(self):
        execute, _result = self._attempt(
            _installed(PINNED), REACHED, fields={"rc": 2, "stdout": "", "stderr": ""}
        )
        self.assertEqual(self._modules(execute), [QUERY, DEB_INSTALL])


if __name__ == "__main__":
    unittest.main()
