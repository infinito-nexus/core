"""INFINITO_PARENT_IMAGE: pkgmgr base image reference composed from
INFINITO_PARENT_IMAGE_OWNER, INFINITO_DISTRO and INFINITO_PARENT_IMAGE_TAG."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_PARENT_IMAGE"
COMMENT = (
    "pkgmgr base image (Dockerfile FROM) composed from "
    "INFINITO_PARENT_IMAGE_OWNER, INFINITO_DISTRO and INFINITO_PARENT_IMAGE_TAG."
)


def compose(owner: str, distro: str, tag: str) -> str:
    return f"ghcr.io/{owner}/pkgmgr-{distro}:{tag}"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(
        KEY,
        compose(
            eb.get("INFINITO_PARENT_IMAGE_OWNER"),
            eb.get("INFINITO_DISTRO"),
            eb.get("INFINITO_PARENT_IMAGE_TAG"),
        ),
        comment=COMMENT,
    )
