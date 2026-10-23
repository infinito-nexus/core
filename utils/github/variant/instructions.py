"""Which matrix entry replays its role's README instructions.

The replay used to be a job of its own, picking one random role per run. It
rides on a deploy row instead, marked with ``instructions`` (the mode the
replay runs in). The job title says nothing about it: the row is an ordinary
deploy of its variant, and the guide host is one more service that variant
pulls in.

Which row carries it is declared, not computed: the role's ``meta/variants.yml``
switches the ``docs`` service on in exactly one variant, and the deploy pulls
the guide host in through that service edge. This module only reads that
declaration back out and turns it into matrix entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.guide import GUIDE_SERVICE_KEY, guide_deployable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


def redundant(entry: Mapping[str, str]) -> bool:
    """Whether the sweep drops this row as coverage an earlier row already has."""
    if entry["priority"] == "true":
        return False
    return entry["clone"] == "true" or entry["covered"] != "0"


def _carries_guide(
    app: str,
    variant: str,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> bool:
    """Whether *app*'s *variant* switches the guide host on."""
    variants = (variants_per_app or {}).get(app) or []
    if not variant.isdigit() or int(variant) >= len(variants):
        return False
    services = (variants[int(variant)] or {}).get("services") or {}
    return (services.get(GUIDE_SERVICE_KEY) or {}).get("enabled") is True


def mark(
    entries: list[dict[str, str]],
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> list[dict[str, str]]:
    """Hand one entry per role the replay.

    Only the first entry of the chosen variant: a priority row runs every mode
    and network mode it offers, and replaying the same README block in each of
    them proves nothing the first replay did not.

    The row has to run in the guide's own mode. The replay is a second deploy
    on the same runner, so hanging it on a swarm row would ask that runner to
    bring a compose stack up beside a swarm one.
    """
    marked: set[str] = set()
    for entry in entries:
        app = entry["apps"]
        if app in marked or redundant(entry):
            continue
        mode = guide_deployable(app)
        if not mode or entry["mode"] != mode:
            continue
        if not _carries_guide(app, entry["variant"], variants_per_app):
            continue
        entry["instructions"] = mode
        marked.add(app)
    return entries
