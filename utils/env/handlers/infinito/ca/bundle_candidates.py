"""INFINITO_CA_BUNDLE_CANDIDATES: where the distributions keep the extracted CA
bundle, read from the group_vars paths SPOT (group_vars/all/05_paths.yml
CA_BUNDLE_CANDIDATES)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.paths import read_group_paths

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CA_BUNDLE_CANDIDATES"
COMMENT = "Extracted CA bundle per distro layout, first readable one wins (SPOT: group_vars/all/05_paths.yml CA_BUNDLE_CANDIDATES)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(
        KEY, " ".join(read_group_paths("CA_BUNDLE_CANDIDATES")), comment=COMMENT
    )
