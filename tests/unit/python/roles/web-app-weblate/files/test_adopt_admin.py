from __future__ import annotations

import contextlib
import io
import os
import runpy
import sys
import unittest
import unittest.mock
from types import ModuleType

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

SCRIPT = PROJECT_ROOT / "roles/web-app-weblate/files/python/adopt_admin.py"
TOKEN_TASKS = PROJECT_ROOT / "roles/web-app-weblate/tasks/utils/token.yml"
DIRECTORY_TASKS = "utils/directory_users.yml"
STOP_MARKER = "ADOPT_REFUSED"
BACKEND = "oidc"
ADMIN = "platformadmin"
SUBJECT = "4f1c2b8e-9d3a-4e57-8a61-0c2d5e7f9b10"
OTHER_SUBJECT = "a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"


def _matches(row, lookups: dict) -> bool:
    return all(getattr(row, key) == value for key, value in lookups.items())


class FakeQuerySet:
    """The QuerySet calls ``adopt_admin.py`` makes.

    Args:
        rows: the model instances the queryset holds.
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, **lookups) -> FakeQuerySet:
        return FakeQuerySet(row for row in self._rows if _matches(row, lookups))

    def exclude(self, **lookups) -> FakeQuerySet:
        return FakeQuerySet(row for row in self._rows if not _matches(row, lookups))

    def first(self):
        return self._rows[0] if self._rows else None

    def exists(self) -> bool:
        return bool(self._rows)

    def get(self, **lookups):
        found = self.filter(**lookups)._rows
        if len(found) != 1:
            raise LookupError(f"{len(found)} rows match {lookups}")
        return found[0]


class FakeManager:
    """A model manager over an in-memory table.

    Args:
        model: the class ``create`` instantiates.
        unique: field names that must be unique together, as ``unique_together``.
    """

    def __init__(self, model, unique: tuple[str, ...] = ()):
        self.model = model
        self.unique = unique
        self.rows: list = []

    def filter(self, **lookups) -> FakeQuerySet:
        return FakeQuerySet(self.rows).filter(**lookups)

    def get(self, **lookups):
        return FakeQuerySet(self.rows).get(**lookups)

    def create(self, **fields):
        key = {name: fields[name] for name in self.unique}
        if self.unique and FakeQuerySet(self.rows).filter(**key).exists():
            raise ValueError(f"unique constraint violated for {key}")
        row = self.model(**fields)
        self.rows.append(row)
        return row


class FakeUser:
    """``weblate.auth.models.User`` reduced to what the adoption touches.

    Args:
        pk: primary key.
        username: login name.
        usable_password: whether ``has_usable_password`` answers True.
    """

    objects: FakeManager

    def __init__(self, pk: int, username: str, *, usable_password: bool = True):
        self.pk = pk
        self.username = username
        self.usable_password = usable_password

    def save(self, update_fields) -> None:
        self.saved = tuple(update_fields)

    def has_usable_password(self) -> bool:
        return self.usable_password

    def set_unusable_password(self) -> None:
        self.usable_password = False


class FakeSocial:
    """``social_django.models.UserSocialAuth`` of social-auth-app-django 7.2.

    Args:
        user: the owning account.
        provider: backend name.
        uid: the identifier the backend reports.
        id_key: the claim ``uid`` was read from; ``social_user`` filters on it.
    """

    objects: FakeManager

    def __init__(self, user, provider: str, uid: str, id_key: str = ""):
        self.user = user
        self.provider = provider
        self.uid = uid
        self.id_key = id_key

    @property
    def user_id(self) -> int:
        return self.user.pk

    def save(self, update_fields) -> None:
        self.saved = tuple(update_fields)


class Database:
    """Fresh model classes and tables, one per test."""

    def __init__(self):
        self.User = type("User", (FakeUser,), {})
        self.User.objects = FakeManager(self.User)
        self.UserSocialAuth = type("UserSocialAuth", (FakeSocial,), {})
        self.UserSocialAuth.objects = FakeManager(
            self.UserSocialAuth, unique=("provider", "uid")
        )

    def user(self, pk: int, username: str, **kwargs):
        return self.User.objects.create(pk=pk, username=username, **kwargs)

    def social(self, user, uid: str, id_key: str = "sub", provider: str = BACKEND):
        return self.UserSocialAuth.objects.create(
            user=user, provider=provider, uid=uid, id_key=id_key
        )

    def modules(self) -> dict[str, ModuleType]:
        auth_models = ModuleType("weblate.auth.models")
        auth_models.User = self.User
        social_models = ModuleType("social_django.models")
        social_models.UserSocialAuth = self.UserSocialAuth
        return {
            "weblate": ModuleType("weblate"),
            "weblate.auth": ModuleType("weblate.auth"),
            "weblate.auth.models": auth_models,
            "social_django": ModuleType("social_django"),
            "social_django.models": social_models,
        }


def adopt(db: Database, *, sso: bool = True, subject: str = SUBJECT) -> str:
    """Run the shipped script the way ``weblate shell`` does and return its stdout.

    Args:
        db: the tables the script reads and writes.
        sso: the value of ``WEBLATE_OIDC_ENABLED``.
        subject: the value of ``WEBLATE_ADMIN_OIDC_UID``.
    """
    env = {
        "WEBLATE_ADMIN_BOOTSTRAP_USERNAME": "admin",
        "WEBLATE_ADMIN_USERNAME": ADMIN,
        "WEBLATE_OIDC_ENABLED": "true" if sso else "false",
        "WEBLATE_OIDC_BACKEND": BACKEND,
        "WEBLATE_ADMIN_OIDC_UID": subject,
    }
    out = io.StringIO()
    with (
        unittest.mock.patch.dict(sys.modules, db.modules()),
        unittest.mock.patch.dict(os.environ, env),
        contextlib.redirect_stdout(out),
    ):
        runpy.run_path(str(SCRIPT), run_name="__weblate_shell__")
    return out.getvalue()


def bindings(db: Database) -> list[tuple[str, str, str, str]]:
    return [
        (row.user.username, row.provider, row.uid, row.id_key)
        for row in db.UserSocialAuth.objects.rows
    ]


class TestAdministratorSubjectBinding(unittest.TestCase):
    def test_the_bootstrapped_superuser_is_bound_to_the_keycloak_subject(self):
        db = Database()
        admin = db.user(1, "admin")
        self.assertIn("ADOPTED=1", adopt(db))
        self.assertEqual(admin.username, ADMIN)
        self.assertEqual(
            bindings(db),
            [(ADMIN, BACKEND, SUBJECT, "sub")],
            "Weblate 2026.11 refuses to link the OIDC sign-in to the local "
            "administrator by e-mail (email_in_use); social_user must find it "
            "through an oidc association on the Keycloak sub instead",
        )
        self.assertFalse(admin.usable_password)

    def test_a_second_run_changes_nothing(self):
        db = Database()
        db.user(1, ADMIN, usable_password=False)
        adopt(db)
        self.assertIn("ADOPTED=0", adopt(db))
        self.assertEqual(bindings(db), [(ADMIN, BACKEND, SUBJECT, "sub")])

    def test_an_unkeyed_legacy_row_for_the_subject_is_keyed_in_place(self):
        db = Database()
        admin = db.user(1, ADMIN, usable_password=False)
        db.social(admin, SUBJECT, id_key="")
        self.assertIn("ADOPTED=1", adopt(db))
        self.assertEqual(bindings(db), [(ADMIN, BACKEND, SUBJECT, "sub")])

    def test_another_account_holding_the_subject_loses_it(self):
        db = Database()
        db.user(1, ADMIN, usable_password=False)
        stray = db.user(2, "platformadmin-old")
        db.social(stray, SUBJECT)
        self.assertIn("ADOPTED=1", adopt(db))
        self.assertEqual(bindings(db), [(ADMIN, BACKEND, SUBJECT, "sub")])

    def test_a_foreign_subject_on_the_administrator_stops_the_run(self):
        db = Database()
        admin = db.user(1, ADMIN, usable_password=False)
        db.social(admin, OTHER_SUBJECT)
        with self.assertRaises(SystemExit) as stop:
            adopt(db)
        self.assertTrue(str(stop.exception.code).startswith(f"{STOP_MARKER}:"))
        self.assertEqual(bindings(db), [(ADMIN, BACKEND, OTHER_SUBJECT, "sub")])

    def test_other_providers_on_the_administrator_are_left_alone(self):
        db = Database()
        admin = db.user(1, ADMIN, usable_password=False)
        db.social(admin, "admin@example.com", id_key="", provider="email")
        adopt(db)
        self.assertEqual(
            sorted(bindings(db)),
            [
                (ADMIN, "email", "admin@example.com", ""),
                (ADMIN, BACKEND, SUBJECT, "sub"),
            ],
        )

    def test_sso_without_a_subject_stops_the_run(self):
        db = Database()
        db.user(1, ADMIN)
        with self.assertRaises(SystemExit) as stop:
            adopt(db, subject="")
        self.assertTrue(str(stop.exception.code).startswith(f"{STOP_MARKER}:"))
        self.assertEqual(bindings(db), [])

    def test_without_sso_nothing_is_bound_and_the_password_stays(self):
        db = Database()
        admin = db.user(1, "admin")
        self.assertIn("ADOPTED=1", adopt(db, sso=False, subject=""))
        self.assertEqual(bindings(db), [])
        self.assertTrue(admin.usable_password)


def _tasks() -> list[dict]:
    return load_yaml_any(str(TOKEN_TASKS), default_if_missing=[])


class TestSubjectReachesTheShell(unittest.TestCase):
    def test_the_keycloak_lookup_runs_only_with_sso(self):
        lookup = next(
            task
            for task in _tasks()
            if any(
                step.get("ansible.builtin.include_role", {}).get("tasks_from")
                == DIRECTORY_TASKS
                for step in task.get("block", [])
            )
        )
        self.assertEqual(lookup["when"], "WEBLATE_OIDC_ENABLED | bool")

    def test_the_adopt_task_forwards_backend_and_subject_into_the_container(self):
        adopt_task = next(
            task
            for task in _tasks()
            if "adopt_admin.py" in str(task.get("ansible.builtin.shell", {}))
        )
        command = adopt_task["ansible.builtin.shell"]["cmd"]
        for name in ("WEBLATE_OIDC_BACKEND", "WEBLATE_ADMIN_OIDC_UID"):
            with self.subTest(name=name):
                self.assertIn(f"-e {name}", command)
                self.assertIn(name, adopt_task["environment"])
        self.assertIn(
            f"'{STOP_MARKER}' in weblate_admin_adopt.stderr", adopt_task["until"]
        )


if __name__ == "__main__":
    unittest.main()
