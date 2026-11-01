import contextlib
import io
import types
import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-weblate" / "files" / "python" / "adopt_admin.py"
)
SUBJECT = "6f1c2a9e-0000-4000-8000-00000000abcd"


class FakeUser:
    def __init__(self, pk, username, usable_password=True):
        self.pk = pk
        self.username = username
        self.usable_password = usable_password
        self.saves = []

    def has_usable_password(self):
        return self.usable_password

    def set_unusable_password(self):
        self.usable_password = False

    def save(self, update_fields):
        self.saves.append(update_fields)


class FakeLink:
    def __init__(self, user, provider, uid):
        self.user = user
        self.provider = provider
        self.uid = uid
        self.saves = []

    @property
    def user_id(self):
        return self.user.pk

    def save(self, update_fields):
        self.saves.append(update_fields)


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeWeblate:
    def __init__(self, users, links=()):
        self.users = users
        self.links = list(links)

    def modules(self):
        backend = self

        class UserManager:
            @staticmethod
            def filter(username):
                return FakeRows(
                    [user for user in backend.users if user.username == username]
                )

            @staticmethod
            def get(username):
                return next(user for user in backend.users if user.username == username)

        class LinkManager:
            @staticmethod
            def filter(provider, uid):
                return FakeRows(
                    [
                        link
                        for link in backend.links
                        if (link.provider, link.uid) == (provider, uid)
                    ]
                )

            @staticmethod
            def create(user, provider, uid):
                backend.links.append(FakeLink(user, provider, uid))

        entries = {
            "weblate": {},
            "weblate.auth": {},
            "weblate.auth.models": {"User": types.SimpleNamespace(objects=UserManager)},
            "social_django": {},
            "social_django.models": {
                "UserSocialAuth": types.SimpleNamespace(objects=LinkManager)
            },
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out


def run(backend, sso=True, subject=SUBJECT):
    env = {
        "WEBLATE_ADMIN_BOOTSTRAP_USERNAME": "admin",
        "WEBLATE_ADMIN_USERNAME": "administrator",
        "WEBLATE_OIDC_ENABLED": "true" if sso else "false",
        "WEBLATE_OIDC_BACKEND": "oidc",
        "WEBLATE_ADMIN_OIDC_UID": subject,
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


class AdoptAdminLinkTests(unittest.TestCase):
    def test_sso_links_the_administrator_to_its_keycloak_subject(self):
        admin = FakeUser(1, "administrator", usable_password=False)
        backend = FakeWeblate([admin])
        self.assertEqual(run(backend), ["ADOPTED=1"])
        self.assertEqual(
            [(link.user, link.provider, link.uid) for link in backend.links],
            [(admin, "oidc", SUBJECT)],
        )

    def test_an_existing_link_of_the_administrator_is_left_alone(self):
        admin = FakeUser(1, "administrator", usable_password=False)
        link = FakeLink(admin, "oidc", SUBJECT)
        backend = FakeWeblate([admin], [link])
        self.assertEqual(run(backend), ["ADOPTED=0"])
        self.assertEqual(backend.links, [link])
        self.assertEqual(link.saves, [])

    def test_a_link_another_account_holds_moves_to_the_administrator(self):
        admin = FakeUser(1, "administrator", usable_password=False)
        stray = FakeUser(2, "administrator1", usable_password=False)
        link = FakeLink(stray, "oidc", SUBJECT)
        backend = FakeWeblate([admin, stray], [link])
        self.assertEqual(run(backend), ["ADOPTED=1"])
        self.assertIs(link.user, admin)
        self.assertEqual(link.saves, [["user"]])

    def test_without_sso_no_link_is_written(self):
        admin = FakeUser(1, "administrator")
        backend = FakeWeblate([admin])
        self.assertEqual(run(backend, sso=False, subject=""), ["ADOPTED=0"])
        self.assertEqual(backend.links, [])
        self.assertTrue(admin.has_usable_password())

    def test_sso_without_a_subject_stops_the_run(self):
        backend = FakeWeblate([FakeUser(1, "administrator", usable_password=False)])
        with self.assertRaises(SystemExit):
            run(backend, subject="")
        self.assertEqual(backend.links, [])

    def test_the_bootstrapped_admin_is_renamed_and_linked(self):
        bootstrap = FakeUser(1, "admin")
        backend = FakeWeblate([bootstrap])
        self.assertEqual(run(backend), ["ADOPTED=1"])
        self.assertEqual(bootstrap.username, "administrator")
        self.assertFalse(bootstrap.has_usable_password())
        self.assertEqual([link.user for link in backend.links], [bootstrap])


if __name__ == "__main__":
    unittest.main()
