"""Compose loop routine: iterate on a local compose deploy of one or more roles.
The role's own unit and fixture tests run before any deploy; an ask step
proposes disabling non-essential providers; deterministic steps run make
compose-deploy around make test; one model step reaches confidence in-container
before the hard verified-in-container gate. A decision node picks the redeploy
from the diff: a fix inside the app role takes make compose-role-sync, which
reaches the role's first task without the constructor, system and provider
stages; a file the inventory bakes in takes a reinstall, because mode=update
reuses the inventory; every other fix takes mode=update. Every path to done
runs an update pass and then the reinstall final gate: a role sync or a plain
fix through the mode=update redeploy, a reinstall through its own full_cycle
pass."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

ROLE_SYNC = "🎯 role sync"
UPDATE = "🌐 mode=update"
REBUILD = "🧱 inventory rebuild"
SYNC_LIMIT = "🚧 sync limit"
_NO_DEPLOY_PREFIXES = ("tests/",)
_NO_DEPLOY_SUFFIXES = (".md", ".rst")
_INVENTORY_FILES = frozenset(
    {
        "meta/variants.yml",
        "meta/services.yml",
        "meta/secrets.yml",
        "meta/users.yml",
    }
)
_OUTSIDE_SYNC_FILES = frozenset(
    {
        "meta/main.yml",
        "meta/info.yml",
        "meta/networks.yml",
        "meta/domains.yml",
        "meta/rbac.yml",
        "meta/mcp.yml",
        "meta/tests.yml",
        "templates/test.env.j2",
    }
)
_OUTSIDE_SYNC_DIRS = ("files/test/",)


def _role_file(path: str) -> tuple[str, str] | None:
    parts = path.split("/", 2)
    if len(parts) == 3 and parts[0] == "roles" and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None


def redeploy_target(role: str, changed_paths: list[str]) -> str:
    """Return the branch label of the redeploy a fix needs.

    A path outside ``roles/<name>/`` that lies under ``tests/`` or is a
    Markdown or reStructuredText file reaches no deploy and is left out, the
    skip rule of ``scripts/meta/resolve/diff/affected_roles.sh``.

    Args:
        role: the application id the loop iterates on.
        changed_paths: the repository-relative paths the fix changed.

    Returns:
        ``REBUILD`` when any path is one of the ``_INVENTORY_FILES`` of any
        role; else ``ROLE_SYNC`` when every remaining path lies under
        ``roles/<role>/`` and is neither one of the ``_OUTSIDE_SYNC_FILES`` nor
        under one of the ``_OUTSIDE_SYNC_DIRS``; else ``UPDATE``, also for an
        empty role or a diff with no remaining path.
    """
    deployed = [
        path
        for path in changed_paths
        if _role_file(path)
        or not (
            path.startswith(_NO_DEPLOY_PREFIXES) or path.endswith(_NO_DEPLOY_SUFFIXES)
        )
    ]
    located = [_role_file(path) for path in deployed]
    if any(found and found[1] in _INVENTORY_FILES for found in located):
        return REBUILD
    if not role or not deployed:
        return UPDATE
    for found in located:
        if (
            found is None
            or found[0] != role
            or found[1] in _OUTSIDE_SYNC_FILES
            or found[1].startswith(_OUTSIDE_SYNC_DIRS)
        ):
            return UPDATE
    return ROLE_SYNC


def _scope(state: dict) -> dict:
    target = redeploy_target(state.get("role", ""), state.get("changed_paths", []))
    if target == ROLE_SYNC and state.get("sync") == SYNC_LIMIT:
        target = UPDATE
    state["scope"] = target
    return state


STEPS = [
    Step(
        "unit",
        "Run the role's unit and fixture tests under tests/unit/*/roles/<role>/ before any deploy; make test waits for the redeploy",
        nxt="disable",
    ),
    Step(
        "disable",
        "Ask to disable matomo, dashboard, prometheus, email and design via disable=",
        "ask",
        nxt="baseline",
    ),
    Step(
        "baseline",
        "make test, then make compose-deploy mode=reinstall apps=<roles> full_cycle=true",
        nxt="inspect",
    ),
    Step(
        "inspect",
        "Reproduce via make compose-exec, reach 95% confidence the fix works",
        "model",
        nxt="fix",
    ),
    Step(
        "fix",
        "Apply the real fix in the repository files, never only in the container",
        nxt="verify",
    ),
    Step(
        "verify",
        "Emit the verified-in-container line, the hard gate before any redeploy",
        nxt="scope",
    ),
    Step(
        "scope",
        "Which redeploy does the diff need? (an inventory-baked meta file: rebuild; only roles/<role>/ outside its shared meta and CLI test files: role sync (after a sync limit: mode=update); else mode=update; tests/ and docs left out)",
        "decision",
        branches=((UPDATE, "redeploy"), (ROLE_SYNC, "sync"), (REBUILD, "rebuild")),
        fn=_scope,
    ),
    Step(
        "sync",
        "Rerun the role's unit tests, then make compose-role-sync role=<role> [variant=<idx>] [task=<file>] [pw=<args>]; task= runs no spec, so pw= needs the whole role; a red from the stages the sync skips is a sync limit",
        branches=(
            ("✅ green", "redeploy"),
            ("❌ red", "inspect"),
            (SYNC_LIMIT, "redeploy"),
        ),
    ),
    Step(
        "rebuild",
        "make test, then make compose-deploy mode=reinstall apps=<roles> full_cycle=true [variant=<idx>], since mode=update reuses the inventory; its full_cycle pass is the update pass",
        branches=(("✅ green", "gate"), ("❌ red", "inspect")),
    ),
    Step(
        "redeploy",
        "make test, then make compose-deploy mode=update apps=<roles> [variant=<idx>] (variant on matrix-variant roles only): mandatory before the gate, after a green role sync too",
        branches=(("✅ green", "gate"), ("❌ red", "inspect")),
    ),
    Step(
        "gate",
        "Final gate once every variant is green: make compose-deploy mode=reinstall apps=<roles> full_cycle=true (no variant)",
        branches=(("✅ green", "done"), ("❌ red", "inspect")),
    ),
    Step("done", "Report the roles green on the stack", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_compose", STEPS)
