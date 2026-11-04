from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import types
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-pretix/files/python/rbac_teams.py"
CLAIM = "groups"
ORGANIZER_GROUP = "/roles/web-app-pretix/organizer"
CHECKIN_GROUP = "/roles/web-app-pretix/checkin"
TEAMS = [
    {
        "name": "Organizers (SSO)",
        "group": ORGANIZER_GROUP,
        "all_event_permissions": True,
        "limit_event_permissions": {},
        "all_organizer_permissions": True,
    },
    {
        "name": "Check-in (SSO)",
        "group": CHECKIN_GROUP,
        "all_event_permissions": False,
        "limit_event_permissions": {"event.orders:checkin": True},
        "all_organizer_permissions": False,
    },
]


class FakeTeam(types.SimpleNamespace):
    def save(self) -> None:
        self.saves += 1


class FakeRuleQuery:
    def __init__(self, backend: FakePretix, rows: list) -> None:
        self.backend = backend
        self.rows = rows

    def exclude(self, **criteria) -> FakeRuleQuery:
        kept = [
            row
            for row in self.rows
            if not all(getattr(row, key) == value for key, value in criteria.items())
        ]
        return FakeRuleQuery(self.backend, kept)

    def delete(self) -> tuple:
        for row in self.rows:
            self.backend.rules.remove(row)
        return len(self.rows), {}


class FakePretix:
    def __init__(self, organizer_slugs: list) -> None:
        self.organizers = [
            types.SimpleNamespace(name=slug, slug=slug, cleaned=False)
            for slug in organizer_slugs
        ]
        self.teams = []
        self.rules = []

    def organizer(self, slug: str) -> object:
        return next(org for org in self.organizers if org.slug == slug)

    def add_team(self, slug: str, name: str, **permissions) -> FakeTeam:
        team = FakeTeam(
            organizer=self.organizer(slug), name=name, saves=0, **permissions
        )
        self.teams.append(team)
        return team

    def add_rule(self, team: FakeTeam, attribute: str, value: str) -> object:
        rule = types.SimpleNamespace(team=team, attribute=attribute, value=value)
        self.rules.append(rule)
        return rule

    def team(self, slug: str, name: str) -> FakeTeam:
        return next(
            team
            for team in self.teams
            if team.organizer.slug == slug and team.name == name
        )

    def rules_of(self, team: FakeTeam) -> list:
        return sorted(
            (rule.attribute, rule.value) for rule in self.rules if rule.team is team
        )

    def modules(self) -> dict:
        backend = self

        class Organizer:
            objects = types.SimpleNamespace(
                exists=lambda: bool(backend.organizers),
                order_by=lambda field: sorted(
                    backend.organizers, key=lambda org: getattr(org, field)
                ),
            )

            def __init__(self, name: str, slug: str) -> None:
                self.name = name
                self.slug = slug
                self.cleaned = False

            def full_clean(self) -> None:
                self.cleaned = True

            def save(self) -> None:
                backend.organizers.append(self)

        team_manager = types.SimpleNamespace(get_or_create=self._team_get_or_create)
        rule_manager = types.SimpleNamespace(
            get_or_create=self._rule_get_or_create,
            filter=lambda team: FakeRuleQuery(
                backend, [rule for rule in backend.rules if rule.team is team]
            ),
        )
        entries = {
            "pretix": {},
            "pretix.base": {},
            "pretix.base.models": {"Organizer": Organizer},
            "pretix.base.models.organizer": {
                "Team": types.SimpleNamespace(objects=team_manager)
            },
            "pretix_oidc": {},
            "pretix_oidc.models": {
                "OIDCTeamAssignmentRule": types.SimpleNamespace(objects=rule_manager)
            },
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out

    def _team_get_or_create(self, organizer, name, defaults) -> tuple:
        for team in self.teams:
            if team.organizer is organizer and team.name == name:
                return team, False
        team = FakeTeam(organizer=organizer, name=name, saves=0, **defaults)
        self.teams.append(team)
        return team, True

    def _rule_get_or_create(self, team, attribute, value) -> tuple:
        for rule in self.rules:
            if (
                rule.team is team
                and rule.attribute == attribute
                and rule.value == value
            ):
                return rule, False
        return self.add_rule(team, attribute, value), True


class TestRbacTeams(unittest.TestCase):
    def exec_script(self, backend: FakePretix, stdout: io.StringIO) -> None:
        env = {
            "RBAC_CLAIM": CLAIM,
            "RBAC_TEAMS": json.dumps(TEAMS),
            "ORGANIZER_NAME": "Infinito.Nexus",
            "ORGANIZER_SLUG": "infinito",
        }
        spec = importlib.util.spec_from_file_location("rbac_teams", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        with (
            patch.dict("os.environ", env),
            patch.dict("sys.modules", backend.modules()),
            contextlib.redirect_stdout(stdout),
        ):
            spec.loader.exec_module(module)

    def run_script(self, backend: FakePretix) -> str:
        stdout = io.StringIO()
        self.exec_script(backend, stdout)
        return stdout.getvalue()

    def test_a_deployment_without_an_organizer_gets_the_deployment_organizer(
        self,
    ) -> None:
        backend = FakePretix([])
        output = self.run_script(backend)
        self.assertEqual(output, "PRETIX_RESULT=CHANGED\n")
        self.assertEqual([org.slug for org in backend.organizers], ["infinito"])
        self.assertEqual(backend.organizers[0].name, "Infinito.Nexus")
        self.assertTrue(backend.organizers[0].cleaned)

    def test_an_existing_organizer_keeps_the_deployment_organizer_away(self) -> None:
        backend = FakePretix(["acme"])
        self.run_script(backend)
        self.assertEqual([org.slug for org in backend.organizers], ["acme"])

    def test_every_organizer_gets_every_team(self) -> None:
        backend = FakePretix(["beta", "acme"])
        self.run_script(backend)
        self.assertEqual(
            sorted((team.organizer.slug, team.name) for team in backend.teams),
            [
                ("acme", "Check-in (SSO)"),
                ("acme", "Organizers (SSO)"),
                ("beta", "Check-in (SSO)"),
                ("beta", "Organizers (SSO)"),
            ],
        )

    def test_a_new_team_carries_the_permissions_of_its_spec_on_all_events(
        self,
    ) -> None:
        backend = FakePretix(["acme"])
        self.run_script(backend)
        checkin = backend.team("acme", "Check-in (SSO)")
        self.assertTrue(checkin.all_events)
        self.assertFalse(checkin.all_event_permissions)
        self.assertEqual(
            checkin.limit_event_permissions, {"event.orders:checkin": True}
        )
        self.assertFalse(checkin.all_organizer_permissions)
        self.assertEqual(checkin.limit_organizer_permissions, {})

    def test_each_team_gets_one_rule_for_its_group_on_the_claim(self) -> None:
        backend = FakePretix(["acme"])
        self.run_script(backend)
        self.assertEqual(
            backend.rules_of(backend.team("acme", "Organizers (SSO)")),
            [(CLAIM, ORGANIZER_GROUP)],
        )
        self.assertEqual(
            backend.rules_of(backend.team("acme", "Check-in (SSO)")),
            [(CLAIM, CHECKIN_GROUP)],
        )

    def test_a_converged_installation_reports_unchanged_without_a_write(
        self,
    ) -> None:
        backend = FakePretix(["acme"])
        self.run_script(backend)
        output = self.run_script(backend)
        self.assertEqual(output, "PRETIX_RESULT=UNCHANGED\n")
        self.assertEqual([team.saves for team in backend.teams], [0, 0])

    def test_drifted_permissions_are_reset_to_the_spec(self) -> None:
        backend = FakePretix(["acme"])
        team = backend.add_team(
            "acme",
            "Organizers (SSO)",
            all_events=False,
            all_event_permissions=True,
            limit_event_permissions={},
            all_organizer_permissions=False,
            limit_organizer_permissions={"organizer.teams:write": True},
        )
        backend.add_rule(team, CLAIM, ORGANIZER_GROUP)
        output = self.run_script(backend)
        self.assertEqual(output, "PRETIX_RESULT=CHANGED\n")
        self.assertTrue(team.all_events)
        self.assertTrue(team.all_organizer_permissions)
        self.assertEqual(team.limit_organizer_permissions, {})
        self.assertEqual(team.saves, 1)

    def test_a_stale_rule_of_a_managed_team_is_deleted(self) -> None:
        backend = FakePretix(["acme"])
        team = backend.add_team(
            "acme",
            "Organizers (SSO)",
            all_events=True,
            all_event_permissions=True,
            limit_event_permissions={},
            all_organizer_permissions=True,
            limit_organizer_permissions={},
        )
        backend.add_rule(team, CLAIM, ORGANIZER_GROUP)
        backend.add_rule(team, CLAIM, "/roles/web-app-pretix/retired")
        backend.add_rule(team, "email", ORGANIZER_GROUP)
        output = self.run_script(backend)
        self.assertIn("PRETIX_RESULT=CHANGED", output)
        self.assertEqual(backend.rules_of(team), [(CLAIM, ORGANIZER_GROUP)])

    def test_a_team_outside_the_spec_keeps_its_rules(self) -> None:
        backend = FakePretix(["acme"])
        manual = backend.add_team(
            "acme",
            "Administrators",
            all_events=True,
            all_event_permissions=True,
            limit_event_permissions={},
            all_organizer_permissions=True,
            limit_organizer_permissions={},
        )
        backend.add_rule(manual, CLAIM, "/roles/web-app-pretix/administrator")
        self.run_script(backend)
        self.assertEqual(
            backend.rules_of(manual), [(CLAIM, "/roles/web-app-pretix/administrator")]
        )
        self.assertEqual(manual.saves, 0)

    def test_a_failure_ends_the_shell_with_a_non_zero_exit_and_no_marker(self) -> None:
        backend = FakePretix(["acme"])

        def refuse(**criteria):
            raise RuntimeError("database is gone")

        backend._team_get_or_create = refuse
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("os._exit", side_effect=SystemExit) as exit_,
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            self.exec_script(backend, stdout)
        exit_.assert_called_once_with(1)
        self.assertNotIn("PRETIX_RESULT", stdout.getvalue())
        self.assertIn("RuntimeError: database is gone", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
