from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from utils.cache import ROLES_DIR
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
    ROLE_FILE_VARS_MAIN,
)

VARS = ROLES_DIR / "web-app-semaphore" / ROLE_FILE_VARS_MAIN
ROLES_VAR = "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_ROLES"
APPLICATION_VAR = "SEMAPHORE_DEPLOY_FIXTURE_APPLICATION"
DATABASES = ("postgres", "mariadb")
ACCOUNT_FILES = (ROLE_FILE_META_SECRETS, ROLE_FILE_META_USERS)
KEYCLOAK = "web-app-keycloak"
REALIGNED = {
    "postgres": (
        (
            "sys-svc-compose",
            "tasks/utils/post_deploy.yml",
            "realign_dedicated_db.yml",
            None,
        ),
        (
            "sys-svc-rdbms",
            "tasks/utils/realign_dedicated_db.yml",
            "set_postgres_superuser_password.sh",
            None,
        ),
    ),
}
ABSORBERS = {
    KEYCLOAK: (
        (
            KEYCLOAK,
            "tasks/00_core.yml",
            "utils/capture_previous_admin.yml",
            "svc-stack",
        ),
        (KEYCLOAK, "tasks/utils/login.yml", "converge/previous_admin.yml", None),
    ),
}


def deployed_roles():
    """Returns:
    The roles a workspace deploy spec deploys, ``SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_ROLES``
    with the fixture application resolved.
    """
    variables = load_yaml_any(str(VARS))
    placeholder = f"{{{{ {APPLICATION_VAR} }}}}"
    return [
        str(role).replace(placeholder, variables[APPLICATION_VAR])
        for role in variables[ROLES_VAR]
    ]


def kept_state(roles_dir, role):
    """Args:
    roles_dir: the roles directory.
    role: a role a spec deploys onto the shared target, alone in its group.

    Returns:
        The credential-guarded state the deploy leaves on the target: a
        ``dedicated`` or ``shared`` database per enabled database service and
        ``accounts`` when the role declares secrets or users.
    """
    services_file = roles_dir / role / ROLE_FILE_META_SERVICES
    services = load_yaml_any(str(services_file)) if services_file.is_file() else {}
    state = []
    for database in DATABASES:
        service = (services or {}).get(database)
        if isinstance(service, dict) and service.get("enabled") not in (False, None):
            kind = "shared" if service.get("shared") is True else "dedicated"
            state.append(f"{kind} {database}")
    if any((roles_dir / role / name).is_file() for name in ACCOUNT_FILES):
        state.append("accounts")
    return state


def marker_findings(roles_dir, checks):
    """Args:
    roles_dir: the roles directory.
    checks: ``(role, path, marker, before)`` tuples; ``marker`` has to
        appear in the file, ahead of ``before`` unless that is None.

    Returns:
        One message per check the file breaks.
    """
    findings = []
    for role, path, marker, before in checks:
        file = roles_dir / role / path
        text = read_text(str(file)) if file.is_file() else ""
        if marker not in text:
            findings.append(f"{role}/{path} no longer holds {marker}")
        elif before is not None and text.find(before) < text.find(marker):
            findings.append(f"{role}/{path} runs {before} before {marker}")
    return findings


def rotation_findings(roles_dir, roles, realigned=REALIGNED, absorbers=ABSORBERS):
    """Args:
    roles_dir: the roles directory.
    roles: the roles the specs deploy onto the shared target.
    realigned: per database type, the checks of the deploy step that moves
        a dedicated engine onto a rotated password.
    absorbers: per role, the checks of the steps that move its accounts onto
        rotated credentials.

    Returns:
        One message per piece of kept state that a deploy with fresh
        credentials, a rotation, would not converge.
    """
    findings = []
    for role in roles:
        for state in kept_state(roles_dir, role):
            kind, _, database = state.partition(" ")
            if kind == "shared":
                findings.append(f"{role}: a shared {database} outlives the workspace")
            elif kind == "dedicated" and database not in realigned:
                findings.append(f"{role}: no deploy realigns a dedicated {database}")
            elif kind == "dedicated":
                findings.extend(marker_findings(roles_dir, realigned[database]))
            elif role not in absorbers:
                findings.append(f"{role}: no step absorbs a rotation of its accounts")
            else:
                findings.extend(marker_findings(roles_dir, absorbers[role]))
    return findings


def planted_roles(tmp):
    """Args:
    tmp: a scratch directory.

    Returns:
        A roles directory holding the files ``rotation_findings`` reads for
        the deployed roles, copied from the real tree.
    """
    roles = Path(tmp) / "roles"
    sources = [
        (role, path)
        for checks in (*REALIGNED.values(), *ABSORBERS.values())
        for role, path, _marker, _before in checks
    ]
    sources += [
        (role, name)
        for role in deployed_roles()
        for name in (ROLE_FILE_META_SERVICES, *ACCOUNT_FILES)
        if (ROLES_DIR / role / name).is_file()
    ]
    for role, path in sources:
        target = roles / role / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROLES_DIR / role / path, target)
    return roles


def replace_in(file, old, new):
    text = file.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    if old not in text:
        raise AssertionError(f"{file} no longer holds {old}")
    file.write_text(text.replace(old, new), encoding="utf-8")


class SharedTargetRotationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.roles = planted_roles(self.scratch.name)

    def test_the_specs_deploy_the_fixture_application_and_keycloak(self):
        self.assertEqual(deployed_roles(), ["web-svc-html", KEYCLOAK])

    def test_only_keycloak_keeps_credential_guarded_state(self):
        self.assertEqual(kept_state(ROLES_DIR, "web-svc-html"), [])
        self.assertEqual(
            kept_state(ROLES_DIR, KEYCLOAK), ["dedicated postgres", "accounts"]
        )

    def test_a_rerun_with_fresh_credentials_is_a_rotation_core_absorbs(self):
        self.assertEqual(rotation_findings(ROLES_DIR, deployed_roles()), [])
        self.assertEqual(rotation_findings(self.roles, deployed_roles()), [])

    def test_negative_control_a_dropped_admin_convergence_is_caught(self):
        replace_in(
            self.roles / KEYCLOAK / "tasks/utils/login.yml",
            "converge/previous_admin.yml",
            "converge/none.yml",
        )
        self.assertEqual(
            rotation_findings(self.roles, deployed_roles()),
            [
                f"{KEYCLOAK}/tasks/utils/login.yml no longer holds converge/previous_admin.yml"
            ],
        )

    def test_negative_control_a_capture_after_the_rerender_is_caught(self):
        core = self.roles / KEYCLOAK / "tasks/00_core.yml"
        replace_in(core, "utils/capture_previous_admin.yml", "utils/none.yml")
        text = core.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        core.write_text(
            f"{text}\n- include_tasks: utils/capture_previous_admin.yml\n",
            encoding="utf-8",
        )
        self.assertEqual(
            rotation_findings(self.roles, deployed_roles()),
            [
                f"{KEYCLOAK}/tasks/00_core.yml runs svc-stack before utils/capture_previous_admin.yml"
            ],
        )

    def test_negative_control_a_dropped_postgres_realign_is_caught(self):
        replace_in(
            self.roles / "sys-svc-compose/tasks/utils/post_deploy.yml",
            "realign_dedicated_db.yml",
            "none.yml",
        )
        self.assertEqual(
            rotation_findings(self.roles, deployed_roles()),
            [
                "sys-svc-compose/tasks/utils/post_deploy.yml no longer holds realign_dedicated_db.yml"
            ],
        )

    def test_negative_control_unabsorbed_state_of_a_new_role_is_caught(self):
        planted = self.roles / "web-app-planted" / "meta"
        planted.mkdir(parents=True)
        (planted / "services.yml").write_text(
            "mariadb:\n  enabled: true\n  shared: false\npostgres:\n  enabled: true\n  shared: true\n",
            encoding="utf-8",
        )
        (planted / "secrets.yml").write_text("credentials: {}\n", encoding="utf-8")
        self.assertEqual(
            rotation_findings(self.roles, ["web-app-planted"]),
            [
                "web-app-planted: a shared postgres outlives the workspace",
                "web-app-planted: no deploy realigns a dedicated mariadb",
                "web-app-planted: no step absorbs a rotation of its accounts",
            ],
        )


if __name__ == "__main__":
    unittest.main()
