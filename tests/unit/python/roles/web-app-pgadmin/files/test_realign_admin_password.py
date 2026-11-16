from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import hmac
import importlib.util
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import types
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

import jinja2
from ansible.plugins.filter.core import b64encode as ansible_b64encode
from passlib.hash import pbkdf2_sha512

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-pgadmin"
SCRIPT_PATH = ROLE / "files/python/realign_admin_password.py"
TASK_FILE = ROLE / "tasks/manager_ops.yml"
ENV_TEMPLATE = ROLE / "templates/env.j2"
CONTAINER = "pgadmin-under-test"
CONFIG_DATABASE_OVERRIDES = (
    "PGADMIN_CONFIG_CONFIG_DATABASE_URI",
    "PGADMIN_CONFIG_SQLITE_PATH",
    "SQLITE_PATH",
)
EMAIL = "administrator@example.org"
PASSWORD = "p$ssw0rd-from-the-users-spot"
AWKWARD = "first line $HOME `id`\nsecond 'single' \"double\" \\n ünïcødé ✓\n  third  "
SALT = "salt-from-the-keys-table"
ROUNDS = 1000
PBKDF2 = pbkdf2_sha512.using(rounds=ROUNDS)
SCHEMA = (
    "CREATE TABLE role (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL UNIQUE);"
    'CREATE TABLE "user" (id INTEGER PRIMARY KEY, email VARCHAR(256),'
    " username VARCHAR(64) NOT NULL UNIQUE, password VARCHAR, active BOOLEAN NOT NULL,"
    " auth_source VARCHAR(16) NOT NULL, login_attempts INTEGER, locked BOOLEAN);"
    "CREATE TABLE roles_users (user_id INTEGER, role_id INTEGER);"
    "CREATE TABLE keys (name VARCHAR NOT NULL PRIMARY KEY, value VARCHAR NOT NULL);"
)


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("realign_admin_password", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signed(secret: str, salt: str) -> bytes:
    """Flask-Security's ``get_hmac``: the input of the double hash.

    Args:
        secret: the normalised password.
        salt: ``SECURITY_PASSWORD_SALT``.

    Returns:
        Base64 of HMAC-SHA512 over ``secret`` keyed with ``salt``.
    """
    return base64.b64encode(
        hmac.new(salt.encode("utf-8"), secret.encode("utf-8"), hashlib.sha512).digest()
    )


def flask_security_hash(password: str, salt: str) -> str:
    """Hash ``password`` as Flask-Security does for ``pbkdf2_sha512``.

    Args:
        password: plaintext password.
        salt: ``SECURITY_PASSWORD_SALT``.

    Returns:
        The passlib ``$pbkdf2-sha512$`` string pgAdmin stores.
    """
    secret = unicodedata.normalize("NFKD", password)
    return PBKDF2.hash(signed(secret, salt).decode("ascii"))


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.matched = []

    def filter_by(self, **criteria):
        self.matched = [
            row
            for row in self.rows
            if all(getattr(row, key) == value for key, value in criteria.items())
        ]
        return self

    def first(self):
        return self.matched[0] if self.matched else None

    def one(self):
        assert len(self.matched) == 1
        return self.matched[0]


class FakeBackend:
    def __init__(self, user=None):
        self.admin = types.SimpleNamespace(id=1, name="Administrator")
        self.user = user
        self.created = []
        self.commits = 0

    def verify_password(self, plain, hashed):
        return hashed == f"hashed-{plain}"

    def hash_password(self, plain):
        return f"hashed-{plain}"

    def normalise_password(self, plain):
        return plain

    def modules(self) -> dict:
        session = types.SimpleNamespace(commit=self._commit)
        entries = {
            "flask_security": {},
            "flask_security.utils": {
                "hash_password": self.hash_password,
                "verify_password": self.verify_password,
            },
            "pgadmin": {},
            "pgadmin.model": {
                "Role": types.SimpleNamespace(query=FakeQuery([self.admin])),
                "User": types.SimpleNamespace(
                    query=FakeQuery([self.user] if self.user else [])
                ),
                "db": types.SimpleNamespace(session=session),
            },
            "pgadmin.tools": {},
            "pgadmin.tools.user_management": {
                "create_user": self._create_user,
                "normalise_password": self.normalise_password,
            },
            "pgadmin.utils": {},
            "pgadmin.utils.constants": {"INTERNAL": "internal"},
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out

    def _create_user(self, data):
        self.created.append(data)
        return True, ""

    def _commit(self):
        self.commits += 1


class PasslibBackend(FakeBackend):
    def __init__(self, user, salt: str):
        super().__init__(user)
        self.salt = salt

    def verify_password(self, plain, hashed):
        return pbkdf2_sha512.verify(signed(plain, self.salt), hashed)

    def hash_password(self, plain):
        return PBKDF2.hash(signed(plain, self.salt).decode("ascii"))

    def normalise_password(self, plain):
        return unicodedata.normalize("NFKD", plain)


def account(**overrides) -> types.SimpleNamespace:
    fields = {
        "email": EMAIL,
        "auth_source": "internal",
        "password": f"hashed-{PASSWORD}",
        "active": True,
        "locked": False,
        "login_attempts": 0,
        "roles": [],
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


@dataclasses.dataclass(frozen=True)
class State:
    """One administrator state, written both as a database and as ORM rows.

    Args:
        hashed_with: password the stored hash was made from.
        hash_salt: salt the stored hash was made with.
        key_salt: ``SECURITY_PASSWORD_SALT`` row of the ``keys`` table.
        active: ``active`` column.
        locked: ``locked`` column.
        administrator: whether ``roles_users`` links the Administrator role.
        auth_source: ``auth_source`` column.
        stored: stored password column; ``None`` derives it from the above.
    """

    hashed_with: str = PASSWORD
    hash_salt: str = SALT
    key_salt: str | None = SALT
    active: bool = True
    locked: bool | None = False
    administrator: bool = True
    auth_source: str = "internal"
    stored: str | None = None

    def password(self) -> str:
        if self.stored is not None:
            return self.stored
        return flask_security_hash(self.hashed_with, self.hash_salt)


CONVERGED = State()
DRIFTED = {
    "a rotated password": State(hashed_with="an-older-secret"),
    "a hash made under another salt": State(hash_salt="a-previous-salt"),
    "a rotated salt key": State(key_salt="a-rotated-salt"),
    "a missing salt key": State(key_salt=None),
    "an inactive account": State(active=False),
    "a locked account": State(locked=True),
    "a missing Administrator role": State(administrator=False),
    "an external account only": State(auth_source="oauth2"),
    "a bcrypt hash": State(stored="$2b$12$" + "a" * 53),
    "a pbkdf2 hash with padded rounds": State(
        stored=flask_security_hash(PASSWORD, SALT).replace(
            f"${ROUNDS}$", f"$0{ROUNDS}$"
        )
    ),
}
COMPARABLE = (
    "a rotated password",
    "a hash made under another salt",
    "a rotated salt key",
    "an inactive account",
    "a locked account",
    "a missing Administrator role",
    "an external account only",
)


def write_database(path: Path, states: list[State]) -> None:
    path.unlink(missing_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO role VALUES (1, 'Administrator'), (2, 'User')")
        salts = {state.key_salt for state in states} - {None}
        for salt in salts:
            connection.execute(
                "INSERT INTO keys VALUES ('SECURITY_PASSWORD_SALT', ?)", (salt,)
            )
        for user_id, state in enumerate(states, start=1):
            connection.execute(
                'INSERT INTO "user" VALUES (?, ?, ?, ?, ?, ?, 0, ?)',
                (
                    user_id,
                    EMAIL,
                    f"account-{user_id}",
                    state.password(),
                    state.active,
                    state.auth_source,
                    state.locked,
                ),
            )
            connection.execute(
                "INSERT INTO roles_users VALUES (?, ?)",
                (user_id, 1 if state.administrator else 2),
            )
        connection.commit()


class DatabaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "pgadmin4.db"

    def in_sync(self, states: list[State], password: str = PASSWORD) -> bool:
        write_database(self.database, states)
        return self.module.in_sync(str(self.database), EMAIL, password)

    def converge(self, state: State, password: str = PASSWORD) -> str:
        admin = types.SimpleNamespace(id=1, name="Administrator")
        backend = PasslibBackend(
            account(
                password=state.password(),
                active=state.active,
                locked=state.locked,
                auth_source=state.auth_source,
                roles=[admin] if state.administrator else [],
            ),
            state.key_salt,
        )
        backend.admin = admin
        with patch.dict("sys.modules", backend.modules()):
            return self.module.converge(EMAIL, password)


class TestConvergeAdministrator(unittest.TestCase):
    def run_script(self, backend: FakeBackend) -> str:
        module = load_script()
        with patch.dict("sys.modules", backend.modules()):
            return module.converge(EMAIL, PASSWORD)

    def test_a_missing_administrator_is_created_with_the_spot_password(self) -> None:
        backend = FakeBackend()
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(backend.created[0]["email"], EMAIL)
        self.assertEqual(backend.created[0]["newPassword"], PASSWORD)
        self.assertEqual(backend.created[0]["role"], backend.admin.id)

    def test_a_rotated_password_reaches_the_existing_administrator(self) -> None:
        backend = FakeBackend()
        backend.user = account(password="hashed-an-older-secret", roles=[backend.admin])
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(backend.user.password, f"hashed-{PASSWORD}")
        self.assertEqual(backend.commits, 1)

    def test_a_locked_administrator_without_the_role_is_repaired(self) -> None:
        backend = FakeBackend()
        backend.user = account(locked=True, login_attempts=3, active=False)
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(
            (backend.user.locked, backend.user.login_attempts, backend.user.active),
            (False, 0, True),
        )
        self.assertIn(backend.admin, backend.user.roles)

    def test_a_converged_administrator_is_left_alone(self) -> None:
        backend = FakeBackend()
        backend.user = account(roles=[backend.admin])
        self.assertEqual(self.run_script(backend), "ok")
        self.assertEqual((backend.created, backend.commits), ([], 0))


class TestPreCheck(DatabaseCase):
    def test_a_converged_administrator_is_in_sync(self) -> None:
        self.assertTrue(self.in_sync([CONVERGED]))

    def test_the_password_is_normalised_before_the_hash(self) -> None:
        composed = "paßwörd-ﬁ-Å"
        self.assertTrue(self.in_sync([State(hashed_with=composed)], composed))

    def test_drift_is_never_reported_in_sync(self) -> None:
        for label, state in DRIFTED.items():
            with self.subTest(label):
                self.assertFalse(self.in_sync([state]))

    def test_two_internal_accounts_on_one_email_go_to_the_application(self) -> None:
        self.assertFalse(self.in_sync([CONVERGED, CONVERGED]))

    def test_a_missing_account_goes_to_the_application(self) -> None:
        self.assertFalse(self.in_sync([]))

    def test_a_missing_database_goes_to_the_application(self) -> None:
        self.assertFalse(self.module.in_sync(str(self.database), EMAIL, PASSWORD))

    def test_an_unreadable_database_goes_to_the_application(self) -> None:
        self.database.write_bytes(b"not a sqlite database at all" * 100)
        self.assertFalse(self.module.in_sync(str(self.database), EMAIL, PASSWORD))

    def test_the_database_is_opened_read_only_and_left_untouched(self) -> None:
        write_database(self.database, [CONVERGED])
        before = self.database.read_bytes()  # nocheck: cache-read tempdir fixture
        uris = []
        real_connect = sqlite3.connect

        def recording_connect(target, *args, **kwargs):
            uris.append((target, kwargs.get("uri")))
            return real_connect(target, *args, **kwargs)

        with patch.object(self.module.sqlite3, "connect", recording_connect):
            self.assertTrue(self.module.in_sync(str(self.database), EMAIL, PASSWORD))
        self.assertEqual(len(uris), 1)
        self.assertTrue(uris[0][0].endswith("?mode=ro"))
        self.assertIs(uris[0][1], True)
        after = self.database.read_bytes()  # nocheck: cache-read tempdir fixture
        self.assertEqual(after, before)


class TestPreCheckAgreesWithConverge(DatabaseCase):
    def test_in_sync_exactly_when_converge_finds_no_drift(self) -> None:
        states = {"converged": CONVERGED}
        states.update((label, DRIFTED[label]) for label in COMPARABLE)
        for label, state in states.items():
            with self.subTest(label):
                self.assertEqual(self.in_sync([state]), self.converge(state) == "ok")

    def test_the_converged_state_is_the_only_one_both_leave_alone(self) -> None:
        self.assertEqual(self.converge(CONVERGED), "ok")
        for label in COMPARABLE:
            with self.subTest(label):
                self.assertEqual(self.converge(DRIFTED[label]), "changed")


def encoded(password: str) -> str:
    return ansible_b64encode(password)


def environment_for(database: Path, **overrides: str) -> dict[str, str]:
    values = dict.fromkeys(CONFIG_DATABASE_OVERRIDES, "")
    values.update(
        PGADMIN_ADMIN_EMAIL=EMAIL,
        PGADMIN_ADMIN_PASSWORD_B64=encoded(PASSWORD),
        PGADMIN_SQLITE_PATH=str(database),
    )
    values.update(overrides)
    return values


def booting(names: list[str]):
    def create_app(name):
        names.append(name)
        return types.SimpleNamespace(test_request_context=contextlib.nullcontext)

    return create_app


def refusing(name):
    raise AssertionError(f"create_app({name!r}) ran although nothing drifted")


class TestMain(DatabaseCase):
    def run_main(self, state: State, create_app, **overrides: str) -> str:
        write_database(self.database, [state])
        admin = types.SimpleNamespace(id=1, name="Administrator")
        backend = PasslibBackend(
            account(password=state.password(), roles=[admin]), SALT
        )
        backend.admin = admin
        modules = backend.modules()
        modules["config"] = types.SimpleNamespace(APP_NAME="pgAdmin 4")
        modules["pgadmin"] = types.SimpleNamespace(create_app=create_app)
        output = io.StringIO()
        with (
            patch.dict("sys.modules", modules),
            patch.dict(os.environ, environment_for(self.database, **overrides)),
            contextlib.redirect_stdout(output),
        ):
            self.module.main()
        return output.getvalue()

    def test_a_converged_administrator_skips_the_application_boot(self) -> None:
        self.assertIn("[UNCHANGED]", self.run_main(CONVERGED, refusing))

    def test_drift_boots_the_application_in_cli_mode(self) -> None:
        names = []
        output = self.run_main(DRIFTED["a rotated password"], booting(names))
        self.assertIn("[CHANGED]", output)
        self.assertEqual(names, ["pgAdmin 4-cli"])

    def test_an_empty_database_path_fails_loudly(self) -> None:
        with (
            patch.dict(
                os.environ, environment_for(self.database, PGADMIN_SQLITE_PATH="")
            ),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            self.module.main()

    def test_an_undecodable_password_fails_without_echoing_it(self) -> None:
        leaked = "pa$$word-sent-raw"
        errors = io.StringIO()
        with (
            patch.dict(
                os.environ,
                environment_for(self.database, PGADMIN_ADMIN_PASSWORD_B64=leaked),
            ),
            contextlib.redirect_stderr(errors),
            self.assertRaises(SystemExit),
        ):
            self.module.main()
        self.assertIn("[FAIL]", errors.getvalue())
        self.assertNotIn("pa$$word", errors.getvalue())

    def test_an_external_config_database_boots_the_application(self) -> None:
        for name in CONFIG_DATABASE_OVERRIDES:
            with self.subTest(name):
                names = []
                output = self.run_main(
                    CONVERGED, booting(names), **{name: "postgresql://db/pgadmin"}
                )
                self.assertIn("[UNCHANGED]", output)
                self.assertEqual(names, ["pgAdmin 4-cli"])


class TestRoleEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script()

    def keys(self, template: str) -> dict[str, str]:
        return dict(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=(.*)$", template))

    def test_the_role_keeps_its_accounts_in_the_sqlite_file(self) -> None:
        template = read_text(str(ENV_TEMPLATE))
        self.assertFalse(self.module.config_database_overridden(self.keys(template)))

    def test_an_env_template_that_moves_the_accounts_disables_the_skip(self) -> None:
        template = read_text(str(ENV_TEMPLATE))
        for name in self.module.CONFIG_DATABASE_OVERRIDES:
            with self.subTest(name):
                redirected = f"{template}\n{name}=postgresql://db/pgadmin\n"
                self.assertTrue(
                    self.module.config_database_overridden(self.keys(redirected))
                )


class TestHashLimits(DatabaseCase):
    def stored_with_salt(self, size: int) -> str:
        salt = b"s" * size
        digest = hashlib.pbkdf2_hmac("sha512", signed(PASSWORD, SALT), salt, ROUNDS, 64)
        salt_text = self.module.ab64_encode(salt)
        checksum = self.module.ab64_encode(digest)
        return f"$pbkdf2-sha512${ROUNDS}${salt_text}${checksum}"

    def test_libpass_accepts_a_1024_byte_salt_and_so_does_the_pre_check(self) -> None:
        stored = self.stored_with_salt(1024)
        self.assertTrue(pbkdf2_sha512.verify(signed(PASSWORD, SALT), stored))
        self.assertTrue(self.in_sync([State(stored=stored)]))

    def test_an_over_long_salt_falls_through_where_libpass_raises(self) -> None:
        stored = self.stored_with_salt(1025)
        with self.assertRaises(ValueError):
            pbkdf2_sha512.verify(signed(PASSWORD, SALT), stored)
        self.assertFalse(self.in_sync([State(stored=stored)]))

    def test_rounds_beyond_libpass_fall_through_without_hashing(self) -> None:
        stored = self.stored_with_salt(16).replace(f"${ROUNDS}$", "$4294967296$")
        with patch.object(
            self.module.hashlib, "pbkdf2_hmac", side_effect=AssertionError("hashed")
        ):
            self.assertFalse(self.in_sync([State(stored=stored)]))


class TestTaskHandover(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "pgadmin4.db"
        shim = self.root / "bin" / "container"
        shim.parent.mkdir()
        shim.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "arguments = sys.argv[1:]\n"
            f"command = arguments[arguments.index({CONTAINER!r}) + 2:]\n"
            "os.execv(sys.executable, [sys.executable, *command])\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        tasks = load_yaml_any(str(TASK_FILE))
        self.task = next(task for task in tasks if "Realign" in task["name"])

    def render(self, source: str, password: str) -> str:
        environment = jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False),
            undefined=jinja2.StrictUndefined,
        )
        environment.filters["b64encode"] = ansible_b64encode
        return environment.from_string(source).render(
            PGADMIN_CONTAINER_ADDRESS=CONTAINER,
            PGADMIN_ADMIN_PASSWORD=password,
            lookup=lambda kind, path: read_text(str(SCRIPT_PATH)).rstrip(),
        )

    def run_task(self, password: str, stdin: str | None = None):
        shell = self.task["ansible.builtin.shell"]
        values = {
            "PGADMIN_ADMIN_EMAIL": EMAIL,
            "PGADMIN_SQLITE_PATH": str(self.database),
        }
        environment = {name: values[name] for name in self.task["environment"]}
        environment["PATH"] = f"{self.root / 'bin'}:/usr/bin:/bin"
        if stdin is None:
            stdin = self.render(shell["stdin"], password) + "\n"
        return subprocess.run(
            ["/bin/sh", "-c", self.render(shell["cmd"], password)],
            input=stdin.encode("utf-8"),
            capture_output=True,
            cwd=self.root,
            env=environment,
            timeout=120,
            check=False,
        )

    def test_any_password_round_trips_intact(self) -> None:
        write_database(self.database, [State(hashed_with=AWKWARD)])
        result = self.run_task(AWKWARD)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"[UNCHANGED]", result.stdout)

    def test_no_fragment_of_the_password_reaches_the_output(self) -> None:
        write_database(self.database, [State(hashed_with="another-password")])
        result = self.run_task(AWKWARD)
        output = (result.stdout + result.stderr).decode("utf-8", "replace")
        for fragment in AWKWARD.splitlines():
            with self.subTest(fragment):
                self.assertNotIn(fragment, output)

    def test_a_missing_password_line_fails_with_a_clean_message(self) -> None:
        result = self.run_task(PASSWORD, stdin="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr.decode().strip(),
            "[FAIL] no administrator password line arrived on stdin.",
        )


if __name__ == "__main__":
    unittest.main()
