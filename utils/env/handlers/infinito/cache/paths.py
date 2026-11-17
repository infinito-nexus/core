"""Host directories the cache stack keeps its state in.

Every one of them sits below the cache base ``BASE_KEY``: the checkout's
``custom.env`` value, else an exported one, else the paths SPOT
(``group_vars/all/05_paths.yml`` ``DIR_CACHE``). The base is written once and
each service names only the leg below it, so a moved base moves every leg, the
tools models and stamps, and the idle units of the infra runner onto another
disk. ``custom.env`` is read before any leg is derived, because the builder
applies it only after every handler and a base set there would otherwise move
alone. The runner's lock, owner marker and bridge record stay in
:func:`machine`, whatever a shell exports, so every caller on the machine
shares them. ``make clean-cache`` removes four of these entries, not the base.

Keys set here: the base, the Nexus blobstore, the frontend's CA directory and
file, its TLS certificates, the registry mirror's data and CA, the shared
package and tool cache folder, and the vulnerability databases.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from utils.env.context import EnvBuilder
from utils.env.parser import parse_static_env
from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.context import BuildContext

CUSTOM_ENV = "custom.env"
BASE_KEY = "INFINITO_INFRA_CACHE_DIR"
BASE_COMMENT = "Cache base every cache path derives from; the infra runner binds it at its host path."
ENTRIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR",
        ("package", "frontend", "ca"),
        "Host directory holding the package-cache frontend CA materials.",
    ),
    (
        "INFINITO_CACHE_PACKAGE_FRONTEND_CA_FILE",
        ("package", "frontend", "ca", "ca.crt"),
        "CA certificate file produced under INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR.",
    ),
    (
        "INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR",
        ("package", "frontend", "certs"),
        "Host directory holding the package-cache frontend TLS certificates.",
    ),
    (
        "INFINITO_CACHE_PACKAGE_HOST_PATH",
        ("package", "data"),
        "Host directory backing the Nexus 3 package-cache blobstore.",
    ),
    (
        "INFINITO_CACHE_REGISTRY_CA_HOST_PATH",
        ("registry", "ca"),
        "Host directory holding the registry-cache proxy CA.",
    ),
    (
        "INFINITO_CACHE_REGISTRY_HOST_PATH",
        ("registry", "mirror"),
        "Host directory backing the registry-cache image mirror.",
    ),
    (
        "INFINITO_CACHE_SHARED_HOST_PATH",
        ("shared",),
        "Host directory every compose slot, swarm lab node and GUI lane mounts at the same path for package and tool caches.",
    ),
    (
        "INFINITO_VULNERABILITY_DB_HOST_PATH",
        ("vulnerability-db",),
        "Host directory every local stack shares for the vulnerability databases.",
    ),
)


def machine() -> Path:
    """Returns:
    The cache base the paths SPOT names, whatever a shell exports: the one
    place every caller on the machine shares the infra runner's lock, owner
    marker and bridge record in.
    """
    return Path(read_group_path("DIR_CACHE"))


def resolve(eb: EnvBuilder, repo_root: Path) -> Path:
    """Args:
        eb: the builder the base is resolved and recorded in.
        repo_root: the checkout whose ``custom.env`` is read.

    Returns:
        The cache base: ``BASE_KEY`` as ``custom.env`` sets it, else as the
        builder resolves an exported value, else :func:`machine`.
    """
    custom = repo_root / CUSTOM_ENV
    pinned = parse_static_env(custom).get(BASE_KEY, "") if custom.is_file() else ""
    if pinned.strip():
        return Path(eb.set(BASE_KEY, pinned.strip(), comment=BASE_COMMENT))
    return Path(eb.setdefault(BASE_KEY, str(machine()), comment=BASE_COMMENT))


def base() -> Path:
    """Returns:
    The cache base at run time: ``BASE_KEY`` as ``make dotenv`` wrote it into
    the environment, which is also what ``compose/infra.yml`` binds, else
    :func:`machine`.
    """
    return Path(EnvBuilder().setdefault(BASE_KEY, str(machine())))


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    root = resolve(eb, ctx.repo_root)
    for key, legs, comment in ENTRIES:
        eb.setdefault(key, str(root.joinpath(*legs)), comment=comment)
