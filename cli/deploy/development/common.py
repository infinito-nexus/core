from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .deps import apps_with_deps, resolve_run_after

if TYPE_CHECKING:
    # Import only for type checking to avoid runtime import cycles.
    from .compose import Compose


# SPOT: canonical repo-relative path to the development vars file that
# `infinito create inventory --vars-file <...>` consumes. Mirrors
# `INVENTORY_VARS_FILE` from scripts/meta/env/inventory.sh; the bash file
# is the SPOT-of-record for callers that go through the deploy chain
# (env is set before Python runs), and the literal here is the fallback
# for direct/test invocations that bypass that chain. A unit test locks
# both literals together so they cannot silently drift.
DEV_INVENTORY_VARS_FILE: str = os.environ.get(
    "INVENTORY_VARS_FILE", "inventories/development/default.yml"
)


VALID_DISTROS: tuple[str, ...] = ("arch", "debian", "ubuntu", "fedora", "centos")


def repo_root_from_here() -> Path:
    # <repo>/cli/deploy/development/common.py -> parents[3] == <repo>
    return Path(__file__).resolve().parents[3]


def resolve_distro() -> str:
    """Return the current INFINITO_DISTRO. Single SPOT for the value.

    The env var is the only input — all CLI subcommands rely on it
    (callers source `scripts/meta/env/defaults.sh` before invocation).
    Raises SystemExit when unset or invalid so a missing setup never
    silently picks the wrong distro.
    """
    distro = os.environ.get("INFINITO_DISTRO", "").strip()
    if not distro:
        raise SystemExit(
            "INFINITO_DISTRO is not set. Source scripts/meta/env/defaults.sh "
            "or export INFINITO_DISTRO=<arch|debian|ubuntu|fedora|centos> "
            "before invoking cli.deploy.development."
        )
    if distro not in VALID_DISTROS:
        raise SystemExit(
            f"INFINITO_DISTRO={distro!r} is not a valid distro. "
            f"Valid: {', '.join(VALID_DISTROS)}."
        )
    return distro


def resolve_container() -> str:
    """Return the current INFINITO_CONTAINER. Single SPOT for the value.

    The env var is kept in lock-step with INFINITO_DISTRO by
    `scripts/meta/env/defaults.sh` (always-derived block outside its
    load-once guard); callers that change INFINITO_DISTRO MUST re-source
    defaults.sh so this stays consistent. Raises SystemExit when unset
    so a missing setup never silently exec's the wrong container.
    """
    container = os.environ.get("INFINITO_CONTAINER", "").strip()
    if not container:
        raise SystemExit(
            "INFINITO_CONTAINER is not set. Source scripts/meta/env/defaults.sh "
            "before invoking cli.deploy.development."
        )
    return container


def make_compose() -> Compose:
    from .compose import Compose

    distro = resolve_distro()
    # Early-fail guard so a missing scripts/meta/env/defaults.sh source
    # surfaces here instead of as a confusing
    # `compose.yml: required variable INFINITO_CONTAINER missing` later.
    # The two env vars must travel together; defaults.sh keeps them in sync.
    resolve_container()
    return Compose(repo_root=repo_root_from_here(), distro=distro)


def resolve_deploy_ids_for_app(compose: Compose, app_id: str) -> list[str]:
    deps = resolve_run_after(compose, app_id)
    return apps_with_deps(app_id, deps_role_names=deps)


def resolve_deploy_ids_for_apps(compose: Compose, app_spec: str) -> list[str]:
    """Resolve deploy ids for one or more space- or comma-separated app ids."""
    app_ids = [a.strip() for a in app_spec.replace(",", " ").split() if a.strip()]
    result: list[str] = []
    for app_id in app_ids:
        for dep in resolve_deploy_ids_for_app(compose, app_id):
            if dep not in result:
                result.append(dep)
    return result
