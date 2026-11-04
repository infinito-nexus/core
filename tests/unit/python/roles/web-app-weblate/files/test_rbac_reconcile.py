import contextlib
import io
import json
import types
import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-weblate"
    / "files"
    / "python"
    / "rbac_reconcile.py"
)
TEAMS = {"reviewer": "Reviewers", "manager": "Managers"}


class FakeGroups:
    def __init__(self, teams):
        self.teams = list(teams)

    def values_list(self, field, flat):
        assert field == "id" and flat
        return [team.id for team in self.teams]

    def add(self, team):
        self.teams.append(team)

    def remove(self, team):
        self.teams.remove(team)


class FakeUser:
    def __init__(self, username, is_superuser=False, is_bot=False, teams=()):
        self.username = username
        self.is_superuser = is_superuser
        self.is_bot = is_bot
        self.groups = FakeGroups(teams)
        self.saves = []
        self.audits = []

    def save(self, update_fields):
        self.saves.append(update_fields)

    def store_audit_state(self):
        self.audits.append("store")

    def log_audit_state(self, request):
        self.audits.append(("log", request))


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, is_bot):
        return FakeQuery([row for row in self.rows if row.is_bot == is_bot])

    def exclude(self, username__in):
        return FakeQuery([row for row in self.rows if row.username not in username__in])

    def order_by(self, field):
        return sorted(self.rows, key=lambda row: getattr(row, field))


class FakeWeblate:
    def __init__(self, users):
        self.users = users
        self.teams = {
            name: types.SimpleNamespace(id=index, name=name)
            for index, name in enumerate(["Users", "Reviewers", "Managers"], start=1)
        }
        self.team_lookups = []

    def modules(self):
        backend = self

        class GroupManager:
            @staticmethod
            def get(**criteria):
                backend.team_lookups.append(criteria)
                return backend.teams[criteria["name"]]

        entries = {
            "django": {},
            "django.conf": {
                "settings": types.SimpleNamespace(ANONYMOUS_USER_NAME="anonymous")
            },
            "weblate": {},
            "weblate.auth": {},
            "weblate.auth.models": {
                "User": types.SimpleNamespace(objects=FakeQuery(self.users)),
                "Group": types.SimpleNamespace(objects=GroupManager),
            },
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out


def member(username):
    return {"username": username, "email": f"{username}@example.org", "name": username}


def run(backend, members, protected=("platformadmin",)):
    env = {
        "RBAC_MEMBERS": json.dumps(
            {"administrator": [], "reviewer": [], "manager": [], **members}
        ),
        "WEBLATE_RBAC_SUPERUSER_ROLE": "administrator",
        "WEBLATE_RBAC_TEAMS": json.dumps(TEAMS),
        "WEBLATE_RBAC_PROTECTED": json.dumps(list(protected)),
    }
    stdout = io.StringIO()
    with (
        patch.dict("sys.modules", backend.modules()),
        patch.dict("os.environ", env, clear=True),
        contextlib.redirect_stdout(stdout),
    ):
        exec(
            compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"),
            {"__name__": "weblate_shell"},
        )
    return stdout.getvalue().splitlines()


class WeblateRbacReconcileTests(unittest.TestCase):
    def test_an_administrator_member_becomes_superuser(self):
        alice = FakeUser("alice")
        output = run(FakeWeblate([alice]), {"administrator": [member("alice")]})

        self.assertEqual(output, ["CHANGED alice superuser=true"])
        self.assertTrue(alice.is_superuser)
        self.assertEqual(alice.saves, [["is_superuser"]])

    def test_a_superuser_outside_the_administrator_group_is_demoted(self):
        mallory = FakeUser("mallory", is_superuser=True)
        output = run(FakeWeblate([mallory]), {})

        self.assertEqual(output, ["CHANGED mallory superuser=false"])
        self.assertFalse(mallory.is_superuser)

    def test_team_members_join_and_outsiders_leave_the_site_teams(self):
        backend = FakeWeblate([])
        bob = FakeUser("bob")
        carol = FakeUser(
            "carol", teams=[backend.teams["Managers"], backend.teams["Users"]]
        )
        backend.users.extend([bob, carol])

        output = run(backend, {"reviewer": [member("bob")]})

        self.assertEqual(output, ["CHANGED bob +Reviewers", "CHANGED carol -Managers"])
        self.assertEqual([team.name for team in bob.groups.teams], ["Reviewers"])
        self.assertEqual([team.name for team in carol.groups.teams], ["Users"])

    def test_only_built_in_site_teams_are_looked_up(self):
        backend = FakeWeblate([FakeUser("bob")])
        run(backend, {})

        self.assertEqual(
            sorted(lookup["name"] for lookup in backend.team_lookups),
            ["Managers", "Reviewers"],
        )
        for lookup in backend.team_lookups:
            self.assertTrue(lookup["internal"])
            self.assertTrue(lookup["defining_project__isnull"])
            self.assertTrue(lookup["defining_workspace__isnull"])

    def test_protected_bot_and_anonymous_accounts_are_never_changed(self):
        admin = FakeUser("platformadmin", is_superuser=True)
        bot = FakeUser("bot-translate", is_superuser=True, is_bot=True)
        anonymous = FakeUser("anonymous")
        output = run(
            FakeWeblate([admin, bot, anonymous]), {"reviewer": [member("anonymous")]}
        )

        self.assertEqual(output, ["UNCHANGED"])
        self.assertTrue(admin.is_superuser)
        self.assertTrue(bot.is_superuser)
        self.assertEqual(anonymous.groups.teams, [])

    def test_a_converged_site_writes_nothing_and_says_so(self):
        backend = FakeWeblate([])
        alice = FakeUser("alice", is_superuser=True, teams=[backend.teams["Managers"]])
        backend.users.append(alice)

        output = run(
            backend, {"administrator": [member("alice")], "manager": [member("alice")]}
        )

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(alice.saves, [])

    def test_every_examined_account_closes_its_audit_state(self):
        alice = FakeUser("alice")
        run(FakeWeblate([alice]), {"administrator": [member("alice")]})

        self.assertEqual(alice.audits, ["store", ("log", None)])


if __name__ == "__main__":
    unittest.main()
