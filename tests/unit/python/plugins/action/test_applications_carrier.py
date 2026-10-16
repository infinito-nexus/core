import unittest
from unittest.mock import patch

from ansible.errors import AnsibleActionFail

from plugins.action.applications_carrier import ActionModule
from utils.cache.carrier import APPLICATIONS_RENDERED_FACT


class _FakeTask:
    def __init__(self, args=None):
        self.args = {} if args is None else dict(args)


class _FakeTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables


class _FakeLookup:
    def __init__(self, carrier, templar=None):
        self.carrier = carrier
        self.templar = templar
        self.calls = []
        self.templar_variables = []

    def run(self, terms, variables=None, **kwargs):
        self.calls.append((terms, variables, kwargs))
        if self.templar is not None:
            self.templar_variables.append(dict(self.templar.available_variables))
        return [self.carrier]


def _make_action(task: _FakeTask, templar=None) -> ActionModule:
    action = object.__new__(ActionModule)
    action._task = task
    action._loader = None
    action._templar = _FakeTemplar() if templar is None else templar
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

    def test_renders_without_the_callers_application_id(self):
        task_vars = {"applications": {}, "application_id": "web-app-bluesky"}
        templar = _FakeTemplar(task_vars)
        lookup = _FakeLookup({"key": ["roles", []], "applications": {}}, templar)
        action = _make_action(_FakeTask(), templar)
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
            patch("plugins.action.applications_carrier.revalidate_tokens_file"),
        ):
            action.run(task_vars=task_vars)

        _, variables, _ = lookup.calls[0]
        self.assertEqual(variables, {"applications": {}})
        self.assertEqual(lookup.templar_variables, [{"applications": {}}])
        self.assertIs(templar.available_variables, task_vars)
        self.assertEqual(task_vars["application_id"], "web-app-bluesky")

    def test_revalidates_the_tokens_file_before_rendering(self):
        order = []
        lookup = _FakeLookup({"key": ["roles", []], "applications": {}})
        lookup.run = lambda *args, **kwargs: order.append("render") or [{}]
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
            patch(
                "plugins.action.applications_carrier.revalidate_tokens_file",
                side_effect=lambda variables: order.append(("revalidate", variables)),
            ),
        ):
            action.run(task_vars={"FILE_TOKENS": "/x/tokens.yml"})

        self.assertEqual(
            order, [("revalidate", {"FILE_TOKENS": "/x/tokens.yml"}), "render"]
        )

    def test_clear_does_not_revalidate(self):
        action = _make_action(_FakeTask(args={"clear": True}))
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.revalidate_tokens_file"
            ) as revalidate,
        ):
            action.run(task_vars={})

        revalidate.assert_not_called()

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

    def test_clear_drops_the_fact_without_rendering(self):
        lookup = _FakeLookup({"key": ["roles", []], "applications": {}})
        action = _make_action(_FakeTask(args={"clear": True}))
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

        self.assertIsNone(result["ansible_facts"][APPLICATIONS_RENDERED_FACT])
        self.assertFalse(result["changed"])
        self.assertEqual(lookup.calls, [])

    def test_clear_false_still_renders(self):
        carrier = {"key": ["roles", ["a", "b", "c", "d"]], "applications": {"x": {}}}
        lookup = _FakeLookup(carrier)
        action = _make_action(_FakeTask(args={"clear": "no"}))
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
        self.assertEqual(len(lookup.calls), 1)


if __name__ == "__main__":
    unittest.main()
