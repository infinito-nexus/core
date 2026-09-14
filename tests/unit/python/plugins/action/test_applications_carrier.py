import unittest
from unittest.mock import patch

from ansible.errors import AnsibleActionFail

from plugins.action.applications_carrier import ActionModule
from utils.cache.carrier import APPLICATIONS_RENDERED_FACT


class _FakeTask:
    def __init__(self, args=None):
        self.args = {} if args is None else dict(args)


class _FakeLookup:
    def __init__(self, carrier):
        self.carrier = carrier
        self.calls = []

    def run(self, terms, variables=None, **kwargs):
        self.calls.append((terms, variables, kwargs))
        return [self.carrier]


def _make_action(task: _FakeTask) -> ActionModule:
    action = object.__new__(ActionModule)
    action._task = task
    action._loader = None
    action._templar = None
    return action


class TestApplicationsCarrierActionPlugin(unittest.TestCase):
    def test_parks_the_carrier_as_a_masked_fact(self):
        carrier = {"key": ["roles", ["a", "b", "c", "d"]], "applications": {"x": {}}}
        lookup = _FakeLookup(carrier)
        action = _make_action(_FakeTask())
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                return_value=lookup,
            ),
        ):
            result = action.run(task_vars={"applications": {}})

        self.assertIs(result["ansible_facts"][APPLICATIONS_RENDERED_FACT], carrier)
        self.assertTrue(result["_ansible_no_log"])
        self.assertFalse(result["changed"])
        terms, variables, kwargs = lookup.calls[0]
        self.assertEqual(terms, [])
        self.assertEqual(variables, {"applications": {}})
        self.assertTrue(kwargs["carrier"])

    def test_rejects_arguments(self):
        action = _make_action(_FakeTask(args={"foo": 1}))
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            self.assertRaises(AnsibleActionFail),
        ):
            action.run(task_vars={})


if __name__ == "__main__":
    unittest.main()
