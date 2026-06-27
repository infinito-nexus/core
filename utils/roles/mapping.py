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

# === Role types =============================================================
# A role's category drives which structural files it may legitimately
# carry. The vocabulary is intentionally small; refine only when a new
# scoping decision genuinely needs a new bucket.
ROLE_TYPE_APPLICATION = "application"
ROLE_TYPE_SYSTEM_SERVICE = "system-service"
ROLE_TYPE_USER = "user"
ROLE_TYPE_TOOLING = "tooling"

# Wildcard type. A ``types`` list entry whose ``type`` is ``ROLE_TYPE_ALL``
# applies to every concrete role type. Concrete-type entries that appear
# alongside the wildcard MUST take precedence so a contributor can spell
# out a single per-type exception without losing the shared default.
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


# === Role file paths ========================================================
# Each constant carries the path of the file relative to the role's own
# directory (``roles/<role-name>/``).
# Standard Ansible role layout
ROLE_FILE_DEFAULTS_MAIN = "defaults/main.yml"
ROLE_FILE_HANDLERS_MAIN = "handlers/main.yml"
ROLE_FILE_TASKS_MAIN = "tasks/main.yml"
ROLE_FILE_VARS_MAIN = "vars/main.yml"
ROLE_FILE_README = "README.md"
ROLE_FILE_TEMPL_COMPOSE = "templates/compose.yml.j2"

# Project-specific meta files
ROLE_FILE_META_MAIN = "meta/main.yml"
ROLE_FILE_META_SERVICES = "meta/services.yml"
ROLE_FILE_META_VARIANTS = "meta/variants.yml"
ROLE_FILE_META_SERVER = "meta/server.yml"
ROLE_FILE_META_RBAC = "meta/rbac.yml"
ROLE_FILE_META_VOLUMES = "meta/volumes.yml"
ROLE_FILE_META_SCHEMA = "meta/schema.yml"
ROLE_FILE_META_INFO = "meta/info.yml"
ROLE_FILE_META_USERS = "meta/users.yml"

# Addons are a directory topic: one `meta/addons/<addon_id>.yml` file per
# addon, the file root being the addon spec. Consumers glob
# ``<role>/meta/addons/*.yml``; the schema + bridge lints under
# ``tests/lint/ansible/services/`` police the per-file contract.
ROLE_DIR_META_ADDONS = "meta/addons"

# Playwright spec: every role's E2E spec ships at this path. Companion
# `.js` helpers MAY live alongside under the same directory; the runner
# (`roles/test-e2e-playwright/tasks/run_one.yml`) globs every `*.js` in
# the directory and stages them into the same tests tree, so a role can
# ship additional modules without further wiring.
ROLE_FILE_PLAYWRIGHT_SPEC = "files/playwright/playwright.spec.js"


# === Per-file scoping =======================================================
# Each entry maps a path constant (the role-relative path) to its
# description and the role types that may legitimately ship the file.
# Each ``types`` entry is a dict with the shape documented in this
# module's docstring (type, file-level mandatory flag, and a list of
# mandatory / optional dotted-path entries inside the file).
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
        # The application and system-service entries declare the type
        # markers consumed by ``utils.roles.type.get_role_type`` and
        # override the wildcard default so the file is mandatory only
        # for those types; everywhere else the file stays optional.
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
        # Mandatory only for application roles (lifecycle declarations
        # are required there); wildcard default keeps it optional for
        # the rest.
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
            "Server-side compose attributes (CSP, domains, status "
            "codes). Only meaningful when the role exposes a deployable "
            "HTTP service."
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
