import unittest
from unittest.mock import patch

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import VariableLayer

from plugins.action.applications_carrier import ActionModule
from utils.cache.carrier import (
    APPLICATIONS_RENDERED_FACT,
    PROVIDER_VIEW_RENDERED_FACT,
    USERS_RENDERED_FACT,
)


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


class _FakeLoader:
    def __init__(self, applications, users):
        self.lookups = {"applications": applications, "users": users}
        self.order = []

    def get(self, name, loader=None, templar=None):
        self.order.append(name)
        return self.lookups[name]


def _make_action(task: _FakeTask, templar=None) -> ActionModule:
    action = object.__new__(ActionModule)
    action._task = task
    action._loader = None
    action._templar = _FakeTemplar() if templar is None else templar
    action.registered = {}
    action.register_host_variables = lambda variables, layer: (
        action.registered.__setitem__(layer, variables)
    )
    return action


def _parked(action: ActionModule) -> dict:
    return action.registered[VariableLayer.EPHEMERAL_FACT]


def _lookups(templar=None):
    applications = _FakeLookup(
        {"key": ["roles", ["a", "b", "c", "d"]], "applications": {"x": {}}}, templar
    )
    users = _FakeLookup(
        {"key": ["roles", ["a", "b", "c", "d", "h"]], "users": {"u": {}}}, templar
    )
    return applications, users, _FakeLoader(applications, users)


class TestApplicationsCarrierActionPlugin(unittest.TestCase):
    def test_parks_both_carriers_outside_the_fact_cache(self):
        applications, users, loader = _lookups()
        action = _make_action(_FakeTask())
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
        ):
            result = action.run(task_vars={"applications": {}})

        self.assertIs(_parked(action)[APPLICATIONS_RENDERED_FACT], applications.carrier)
        self.assertIs(_parked(action)[USERS_RENDERED_FACT], users.carrier)
        self.assertEqual(action.registered[VariableLayer.CACHEABLE_FACT], {})
        self.assertNotIn("ansible_facts", result)
        self.assertTrue(result["_ansible_no_log"])
        self.assertFalse(result["changed"])
        for lookup in (applications, users):
            terms, variables, kwargs = lookup.calls[0]
            self.assertEqual(terms, [])
            self.assertEqual(variables, {"applications": {}})
            self.assertTrue(kwargs["carrier"])

    def _park(self, task_vars):
        applications, users, loader = _lookups()
        action = _make_action(_FakeTask())
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
            patch("plugins.action.applications_carrier.revalidate_tokens_file"),
        ):
            action.run(task_vars=task_vars)
        return _parked(action), applications, users

    def test_a_users_carrier_that_still_matches_stays_in_place(self):
        parked = {"key": ["roles", ["a", "b", "c", "d", "h"]], "users": {"u": {}}}
        carriers, applications, _ = self._park({USERS_RENDERED_FACT: parked})

        self.assertNotIn(USERS_RENDERED_FACT, carriers)
        self.assertIs(carriers[APPLICATIONS_RENDERED_FACT], applications.carrier)

    def test_a_stale_users_carrier_is_replaced(self):
        parked = {"key": ["roles", ["a", "b", "c", "d", "h2"]], "users": {"u": {}}}
        carriers, _, users = self._park({USERS_RENDERED_FACT: parked})

        self.assertIs(carriers[USERS_RENDERED_FACT], users.carrier)

    def test_renders_the_applications_before_the_users(self):
        _, _, loader = _lookups()
        action = _make_action(_FakeTask())
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
            patch("plugins.action.applications_carrier.revalidate_tokens_file"),
        ):
            action.run(task_vars={})

        self.assertEqual(loader.order, ["applications", "users"])

    def test_renders_without_the_callers_application_id(self):
        task_vars = {"applications": {}, "application_id": "web-app-bluesky"}
        templar = _FakeTemplar(task_vars)
        applications, users, loader = _lookups(templar)
        action = _make_action(_FakeTask(), templar)
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
            patch("plugins.action.applications_carrier.revalidate_tokens_file"),
        ):
            action.run(task_vars=task_vars)

        for lookup in (applications, users):
            _, variables, _ = lookup.calls[0]
            self.assertEqual(variables, {"applications": {}})
            self.assertEqual(lookup.templar_variables, [{"applications": {}}])
        self.assertIs(templar.available_variables, task_vars)
        self.assertEqual(task_vars["application_id"], "web-app-bluesky")

    def test_revalidates_the_tokens_file_before_rendering(self):
        order = []
        applications, users, loader = _lookups()
        applications.run = lambda *args, **kwargs: (
            order.append("applications") or [applications.carrier]
        )
        users.run = lambda *args, **kwargs: order.append("users") or [users.carrier]
        action = _make_action(_FakeTask())
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
            patch(
                "plugins.action.applications_carrier.revalidate_tokens_file",
                side_effect=lambda variables: order.append(("revalidate", variables)),
            ),
        ):
            action.run(task_vars={"FILE_TOKENS": "/x/tokens.yml"})

        self.assertEqual(
            order,
            [("revalidate", {"FILE_TOKENS": "/x/tokens.yml"}), "applications", "users"],
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

    def test_clear_drops_every_carrier_without_rendering(self):
        applications, users, loader = _lookups()
        action = _make_action(_FakeTask(args={"clear": True}))
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
        ):
            result = action.run(task_vars={"applications": {}})

        self.assertEqual(
            _parked(action),
            {
                APPLICATIONS_RENDERED_FACT: None,
                USERS_RENDERED_FACT: None,
                PROVIDER_VIEW_RENDERED_FACT: None,
            },
        )
        self.assertEqual(action.registered[VariableLayer.CACHEABLE_FACT], {})
        self.assertNotIn("ansible_facts", result)
        self.assertFalse(result["changed"])
        self.assertEqual(applications.calls, [])
        self.assertEqual(users.calls, [])

    def test_clear_false_still_renders(self):
        applications, users, loader = _lookups()
        action = _make_action(_FakeTask(args={"clear": "no"}))
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
        ):
            action.run(task_vars={"applications": {}})

        self.assertIs(_parked(action)[APPLICATIONS_RENDERED_FACT], applications.carrier)
        self.assertIs(_parked(action)[USERS_RENDERED_FACT], users.carrier)
        self.assertEqual(len(applications.calls), 1)
        self.assertEqual(len(users.calls), 1)

    def _run_with_view_carrier(self, args, view_carrier):
        _applications, _users, loader = _lookups()
        action = _make_action(_FakeTask(args=args))
        task_vars = {"applications": {}, "inventory_hostname": "wrk"}
        with (
            patch(
                "plugins.action.applications_carrier.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch(
                "plugins.action.applications_carrier.lookup_loader.get",
                side_effect=loader.get,
            ),
            patch(
                "plugins.action.applications_carrier.provider_view_carrier",
                return_value=view_carrier,
            ) as probe,
        ):
            action.run(task_vars=task_vars)
        return _parked(action), probe, action, task_vars

    def test_provider_view_parks_the_provider_view_carrier(self):
        view_carrier = {"key": ["roles", []], "applications": {}, "view": ["mgr", ""]}

        carriers, probe, action, task_vars = self._run_with_view_carrier(
            {"provider_view": True}, view_carrier
        )

        probe.assert_called_once_with(task_vars, templar=action._templar)
        self.assertIs(carriers[PROVIDER_VIEW_RENDERED_FACT], view_carrier)

    def test_a_provider_view_carrier_that_still_matches_stays_in_place(self):
        carriers, probe, _, _ = self._run_with_view_carrier(
            {"provider_view": True}, None
        )

        probe.assert_called_once()
        self.assertNotIn(PROVIDER_VIEW_RENDERED_FACT, carriers)

    def test_without_provider_view_the_view_is_not_rendered(self):
        carriers, probe, _, _ = self._run_with_view_carrier({}, {"key": []})

        probe.assert_not_called()
        self.assertNotIn(PROVIDER_VIEW_RENDERED_FACT, carriers)


if __name__ == "__main__":
    unittest.main()
