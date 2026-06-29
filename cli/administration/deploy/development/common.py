from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import PROJECT_ROOT
from .deps import apps_with_deps, resolve_run_after
from .env import resolve_distro

if TYPE_CHECKING:
    from .compose import Compose


# Mirrors INFINITO_INVENTORY_VARS_FILE from default.env; drift-guarded.
DEV_INVENTORY_VARS_FILE: str = (
    os.environ.get("INFINITO_INVENTORY_VARS_FILE")
    or "inventories/development/default.yml"
)


def resolve_container() -> str:
    """Return INFINITO_CONTAINER; raise SystemExit if unset."""
    container = os.environ["INFINITO_CONTAINER"].strip()
    if not container:
        raise SystemExit(
            "INFINITO_CONTAINER is not set. Run 'make dotenv' (or source scripts/meta/env/load.sh) "
            "before invoking cli.administration.deploy.development."
        )
    return container


def make_compose() -> Compose:
    from .compose import Compose

    distro = resolve_distro()
    # Surface env-script gap here rather than as a cryptic compose error later.
    resolve_container()
    return Compose(repo_root=PROJECT_ROOT, distro=distro)


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
