from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError

from cli.administration.inventory.credentials.schema import (
    DEFAULT,
    credential_schema,
)
from utils.cache import ROLES_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

USERS = "users"
APPS = "apps"
USER_FIELD = "password"
OBJSTORE_FIELD = "objstore_secret_key"
REFERENCE_KEY = "openbao"


def semaphore_fixture_secrets(
    credentials: Mapping[str, Any],
    root: str,
    running: Iterable[str],
    objstore_consumers: Iterable[str],
) -> list[dict[str, Any]]:
    """Args:
        credentials: ``SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_CREDENTIALS``, the
            ``users`` and the ``applications`` with their credential names the
            workspace roles read on the platform host.
        root: the KV v2 folder of the platform host below the mount,
            ``fixture/<host>``.
        running: the applications the platform host runs, its ``group_names``.
        objstore_consumers: the applications whose ``objstore_secret_key`` the
            shared object store renders, empty without one.

    Returns:
        One entry per KV v2 secret, users before applications and each sorted:
        ``kind`` (``users`` or ``apps``), ``name``, ``path`` below the mount and
        the sorted ``fields`` it holds. An application the host does not run
        has none.
    """
    running = set(running)
    applications: dict[str, set[str]] = {}
    for application_id, names in (credentials.get("applications") or {}).items():
        applications.setdefault(str(application_id), set()).update(map(str, names))
    for application_id in objstore_consumers:
        applications.setdefault(str(application_id), set()).add(OBJSTORE_FIELD)
    entries = [
        {
            "kind": USERS,
            "name": str(name),
            "path": f"{root}/{USERS}/{name}",
            "fields": [USER_FIELD],
        }
        for name in sorted({str(name) for name in credentials.get("users") or []})
    ]
    entries.extend(
        {
            "kind": APPS,
            "name": application_id,
            "path": f"{root}/{APPS}/{application_id}",
            "fields": sorted(fields),
        }
        for application_id, fields in sorted(applications.items())
        if application_id in running and fields
    )
    return entries


def semaphore_fixture_references(
    secrets: Iterable[Mapping[str, Any]], mount: str
) -> dict[str, Any]:
    """Args:
        secrets: the result of ``semaphore_fixture_secrets``.
        mount: the KV v2 mount the secrets live in.

    Returns:
        The vars of the platform host as the fixture commits them: every user
        password and application credential of ``secrets`` as an OpenBao
        reference ``{openbao: <mount>/<path>#<field>}``, and no value.
    """
    users: dict[str, Any] = {}
    applications: dict[str, Any] = {}
    for secret in secrets:
        references = {
            field: {REFERENCE_KEY: f"{mount}/{secret['path']}#{field}"}
            for field in secret["fields"]
        }
        if secret["kind"] == USERS:
            users[secret["name"]] = references
        else:
            applications[secret["name"]] = {"secrets": {"credentials": references}}
    return {USERS: users, "applications": applications}


def semaphore_fixture_fields(
    credentials: Mapping[str, Any], secret: Mapping[str, Any]
) -> dict[str, Any]:
    """Args:
        credentials: ``secrets.credentials`` of the application ``secret``
            names, as the live inventory resolves it.
        secret: one ``apps`` entry of ``semaphore_fixture_secrets``.

    Returns:
        The fields the entry names with their live values, refused when the
        application lacks one of them.
    """
    missing = [field for field in secret["fields"] if field not in credentials]
    if missing:
        raise AnsibleFilterError(
            f"semaphore_fixture_fields: {secret['name']} holds no credential "
            f"{', '.join(missing)} the fixture of {secret['path']} needs"
        )
    return {field: credentials[field] for field in secret["fields"]}


def semaphore_fixture_credential_schemas(roles: Iterable[str]) -> dict[str, Any]:
    """Args:
        roles: the roles a workspace deploy spec deploys.

    Returns:
        ``{role: schema}``, the ``credential_schema`` of each role on its own:
        paths, fields and generator kinds, never a value. A ``default`` the
        role declares travels as ``default_b64``, so no template text reaches
        the rendered file.
    """
    schemas = {}
    for role in roles:
        schema = credential_schema(ROLES_DIR, [str(role)])
        for entry in schema["credentials"]:
            if DEFAULT in entry:
                entry["default_b64"] = base64.b64encode(
                    entry.pop(DEFAULT).encode()
                ).decode()
        schemas[str(role)] = schema
    return schemas


class FilterModule:
    def filters(self):
        return {
            "semaphore_fixture_secrets": semaphore_fixture_secrets,
            "semaphore_fixture_references": semaphore_fixture_references,
            "semaphore_fixture_fields": semaphore_fixture_fields,
            "semaphore_fixture_credential_schemas": semaphore_fixture_credential_schemas,
        }
