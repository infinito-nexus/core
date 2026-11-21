from __future__ import annotations

from typing import TYPE_CHECKING

from utils.design.gallery import GALLERY_ROOT, app_gallery, gaps, manifest

if TYPE_CHECKING:
    from collections.abc import MutableMapping

GALLERY_COMMAND = "make design-gallery app=<app>"
MANIFEST_COMMAND = "python -m cli.meta.roles.design.gallery manifest <app>"


def collect(state: MutableMapping) -> MutableMapping:
    """Write the manifest and the gaps of every app gallery the state names.

    Args:
        state: reads ``apps``, the application ids whose screenshots
            ``GALLERY_COMMAND`` captured; writes ``gallery`` as
            ``{app: {"manifest": ..., "gaps": [...]}}``.
    """
    collected = {}
    for app in state.get("apps") or []:
        shots = manifest(app_gallery(GALLERY_ROOT, app))
        collected[app] = {"manifest": shots, "gaps": gaps(shots)}
    state["gallery"] = collected
    return state
