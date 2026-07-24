"""Role mapping SPOT.

This module is the single source of truth for role-level dependencies:
the paths inside a role directory, the role types each path may
legitimately appear under, the mandatory shape of those paths, and the
``marker`` entries that drive role-type detection itself. Both lint
tests and the role-type predicate live downstream of this file:

* lint tests import :data:`ROLE_FILES` to forbid type-scoped artefacts
  on the wrong role type, to assert that mandatory files are present,
  and to assert that mandatory dotted-path entries inside those files
  exist;
* the role-type predicate lives in :mod:`utils.roles.type` (see
  :func:`utils.roles.type.get_role_type`) and walks the ``marker``
  flag in this file's ``entries`` to derive a role's type from the
  values declared in its own files.

Path constants
--------------

Every ``ROLE_FILE_*`` constant carries the file's path relative to the
role directory itself (``roles/<role-name>/``). Callers compose the
absolute path by joining with the resolved role directory::

    from utils.roles.mapping import ROLE_FILE_META_SERVICES

    services_path = (
        PROJECT_ROOT / "roles" / "web-app-matomo" / ROLE_FILE_META_SERVICES
    )

Type vocabulary and shape
-------------------------

``ROLE_TYPE_*`` constants name the role categories the project
distinguishes. Each ``ROLE_FILES[<path>]['types']`` value is a list of
type-scoping entries with the shape::

    {
        "type":      <ROLE_TYPE_*>,
        "mandatory": <bool>,                # MUST the file/entry be set
        "allowed":   <bool>,                # MAY the file/entry be set
        "entries": [                        # dotted-path facts about the file
            {
                "path":      "application_id",
                "mandatory": True,
                "allowed":   True,
                "marker":    True,          # the role IS this type when set
            },
            {
                "path":      "ports.local.http",
                "mandatory": False,
                "allowed":   True,
            },
        ],
    }

Two complementary flags control the per-type policy:

* ``mandatory`` (default ``False``): the file (or dotted-path entry)
  MUST be present and non-empty for a role of this type. Implies
  ``allowed: True``; setting ``mandatory: True`` together with
  ``allowed: False`` is a schema error.
* ``allowed`` (default ``True``): the file (or dotted-path entry)
  MAY be present for a role of this type. Set ``allowed: False`` to
  forbid the file/entry on roles of this type so the lint layer can
  surface the offence with a precise reason.

Roles whose type set does not match any explicit entry inherit the
type's policy from the wildcard fallback (see below); without a
wildcard the file/entry is implicitly forbidden.

``entries`` is a list of dotted-path facts about the file's content.
Each entry carries the same ``mandatory`` and ``allowed`` semantics
described above and adds a ``marker`` flag (default ``False``):
``marker: True`` declares the path as the type marker for the
surrounding type entry. :func:`utils.roles.type.get_role_types` walks
every ``marker: True`` entry; each marker that resolves to a non-empty
value in the role's file adds the surrounding type to the role's type
set. ``application_id`` for ``application`` and ``system_service_id``
for ``system-service`` are the canonical markers.

Wildcard ``ROLE_TYPE_ALL`` collapses repetition: a single entry with
``"type": ROLE_TYPE_ALL`` applies to every concrete role type. A
concrete-type entry that appears alongside the wildcard MUST take
precedence so a contributor can spell out one per-type exception
without losing the shared default.
"""

from __future__ import annotations

ROLE_TYPE_APPLICATION = "application"
ROLE_TYPE_SYSTEM_SERVICE = "system-service"
ROLE_TYPE_USER = "user"
ROLE_TYPE_TOOLING = "tooling"

ROLE_TYPE_ALL = "all"

ROLE_TYPES: tuple[str, ...] = (
    ROLE_TYPE_APPLICATION,
    ROLE_TYPE_SYSTEM_SERVICE,
    ROLE_TYPE_USER,
    ROLE_TYPE_TOOLING,
)


def _all(
    *,
    mandatory: bool = False,
    allowed: bool = True,
    entries: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Return a single :data:`ROLE_TYPE_ALL` wildcard entry.

    Use for files whose policy is the same across every role type.

    * ``mandatory`` flips the must-set policy on for every type.
    * ``allowed`` flips the may-set policy off for every type when
      ``False`` (use this in combination with concrete-type overrides
      to express "this file is forbidden everywhere except for the
      explicitly listed types").
    * ``entries`` attaches per-path facts that apply to every type.

    Setting ``mandatory: True`` together with ``allowed: False`` is a
    schema error and raises :class:`ValueError` so contributors can't
    accidentally encode a contradiction in the SPOT.
    """
    if mandatory and not allowed:
        raise ValueError(
            "_all(): mandatory=True with allowed=False is contradictory; "
            "a forbidden file cannot also be required."
        )
    return [
        {
            "type": ROLE_TYPE_ALL,
            "mandatory": mandatory,
            "allowed": allowed,
            "entries": list(entries or []),
        }
    ]


ROLE_FILE_DEFAULTS_MAIN = "defaults/main.yml"
ROLE_FILE_HANDLERS_MAIN = "handlers/main.yml"
ROLE_FILE_TASKS_MAIN = "tasks/main.yml"
ROLE_FILE_VARS_MAIN = "vars/main.yml"
ROLE_FILE_README = "README.md"
ROLE_FILE_TEMPL_COMPOSE = "templates/compose.yml.j2"
ROLE_GLOB_TEMPL_COMPOSE_SIBLINGS = "templates/*.compose.yml.j2"
ROLE_GLOB_TEMPL_COMPOSE_VARIANTS = "templates/compose.*.yml.j2"


def role_is_stack(role_dir) -> bool:
    """True when the role renders a docker stack.

    Args:
        role_dir: path-like of the role directory (``roles/<name>``).

    A role is a stack role iff it ships ``templates/compose.yml.j2``,
    any ``templates/*.compose.yml.j2`` sibling, or a
    ``templates/compose.*.yml.j2`` variant such as
    ``compose.override.yml.j2``.
    """
    from pathlib import Path

    root = Path(role_dir)
    return (
        (root / ROLE_FILE_TEMPL_COMPOSE).exists()
        or any(root.glob(ROLE_GLOB_TEMPL_COMPOSE_SIBLINGS))
        or any(root.glob(ROLE_GLOB_TEMPL_COMPOSE_VARIANTS))
    )


ROLE_FILE_META_MAIN = "meta/main.yml"
ROLE_FILE_META_SERVICES = "meta/services.yml"
ROLE_FILE_META_VARIANTS = "meta/variants.yml"
ROLE_FILE_META_SERVER = "meta/server.yml"
ROLE_FILE_META_CSP = "meta/csp.yml"
ROLE_FILE_META_DOMAINS = "meta/domains.yml"
ROLE_FILE_META_NETWORKS = "meta/networks.yml"
ROLE_FILE_META_RBAC = "meta/rbac.yml"
ROLE_FILE_META_VOLUMES = "meta/volumes.yml"
ROLE_FILE_META_SCHEMA = "meta/schema.yml"
ROLE_FILE_META_INFO = "meta/info.yml"
ROLE_FILE_META_USERS = "meta/users.yml"
ROLE_FILE_META_TESTS = "meta/tests.yml"

ROLE_DIR_META_ADDONS = "meta/addons"

ROLE_FILE_PLAYWRIGHT_SPEC = "files/playwright/playwright.spec.js"


ROLE_FILES: dict[str, dict[str, object]] = {
    ROLE_FILE_DEFAULTS_MAIN: {
        "description": ("Default values for role variables, overridable by callers."),
        "types": _all(mandatory=False),
    },
    ROLE_FILE_HANDLERS_MAIN: {
        "description": "Ansible handler tasks invoked via ``notify:``.",
        "types": _all(mandatory=False),
    },
    ROLE_FILE_TASKS_MAIN: {
        "description": ("Entry-point task list executed when the role runs."),
        "types": _all(mandatory=True),
    },
    ROLE_FILE_VARS_MAIN: {
        "description": (
            "Role-local variables; the canonical home of the role's "
            "type marker (``application_id`` or ``system_service_id``)."
        ),
        "types": [
            {
                "type": ROLE_TYPE_APPLICATION,
                "mandatory": True,
                "entries": [
                    {
                        "path": "application_id",
                        "mandatory": True,
                        "marker": True,
                    },
                ],
            },
            {
                "type": ROLE_TYPE_SYSTEM_SERVICE,
                "mandatory": True,
                "entries": [
                    {
                        "path": "system_service_id",
                        "mandatory": True,
                        "marker": True,
                    },
                ],
            },
            *_all(mandatory=False),
        ],
    },
    ROLE_FILE_README: {
        "description": (
            "Human-facing README. Required for application roles by "
            "the Web App Dashboard, optional elsewhere."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": True, "entries": []},
            *_all(mandatory=False),
        ],
    },
    ROLE_FILE_TEMPL_COMPOSE: {
        "description": (
            "Docker Compose template rendered by sys-svc-compose; "
            "carries the per-role service spec and named volumes."
        ),
        "types": _all(mandatory=False),
    },
    ROLE_FILE_META_MAIN: {
        "description": (
            "Galaxy metadata and Ansible meta dependencies; required "
            "by the Ansible role machinery."
        ),
        "types": _all(
            mandatory=True,
            entries=[{"path": "galaxy_info.description", "mandatory": True}],
        ),
    },
    ROLE_FILE_META_SERVICES: {
        "description": (
            "Compose services map keyed by entity. Carries "
            "``lifecycle``, ``run_after`` and per-service "
            "port/credential definitions."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": True, "entries": []},
            *_all(mandatory=False),
        ],
    },
    ROLE_FILE_META_VARIANTS: {
        "description": (
            "Matrix-deploy variant overrides. Only iterated for primary "
            "apps addressable via ``--apps``."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_SERVER: {
        "description": (
            "Server-side proxy attributes (status codes, locations, body "
            "size limits). Only meaningful when the role exposes a "
            "deployable HTTP service."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_CSP: {
        "description": (
            "Content-Security-Policy flags and per-directive whitelist for "
            "the application's HTTP responses."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_DOMAINS: {
        "description": (
            "Public domain declarations (canonical, aliases) for the "
            "application's web-accessible service."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_NETWORKS: {
        "description": (
            "Docker network declarations (per-network subnets, overlay "
            "topology) for the application's compose stack."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_RBAC: {
        "description": (
            "RBAC declarations for the application's Keycloak realm and oauth2 layer."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_VOLUMES: {
        "description": (
            "Compose volume declarations for the application's container stack."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_SCHEMA: {
        "description": (
            "Application config schema describing credentials and validation rules."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
    ROLE_FILE_META_INFO: {
        "description": ("Optional dashboard / UI metadata (logo, label) for the role."),
        "types": _all(mandatory=False),
    },
    ROLE_FILE_META_USERS: {
        "description": (
            "Reserved-username declarations consumed by the user-management layer."
        ),
        "types": _all(mandatory=False),
    },
    ROLE_FILE_PLAYWRIGHT_SPEC: {
        "description": (
            "E2E Playwright spec staged by the test-e2e-playwright role. "
            "Companion `.js` helpers MAY live alongside under "
            "``files/playwright/`` and are staged into the same tests "
            "directory automatically."
        ),
        "types": [
            {"type": ROLE_TYPE_APPLICATION, "mandatory": False, "entries": []},
            *_all(allowed=False),
        ],
    },
}
