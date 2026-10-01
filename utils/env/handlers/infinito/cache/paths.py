"""Host directories the cache stack keeps its state in.

Every one of them sits below the cache base the paths SPOT defines
(``group_vars/all/05_paths.yml`` ``DIR_CACHE``), so the base is written once
and each service names only the leg below it. ``make clean-cache`` removes
three of these entries, not the base.

Keys set here: the Nexus blobstore, the frontend's CA directory and file, its
TLS certificates, and the registry mirror's data and CA.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

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
)


def base() -> Path:
    """Return the cache base every entry below it derives from."""
    return Path(read_group_path("DIR_CACHE"))


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    root = base()
    for key, legs, comment in ENTRIES:
        eb.setdefault(key, str(root.joinpath(*legs)), comment=comment)
