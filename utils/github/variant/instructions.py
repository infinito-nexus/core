"""Which matrix entry replays its role's README instructions.

The replay used to be a job of its own, picking one random role per run. It
rides on a deploy row instead: the role's smallest variant among the rows this
sweep actually deploys, marked with ``instructions`` (the mode the replay runs
in) and a 📖 in the job title. :mod:`utils.roles.guide` decides which variant
that is; this module is what turns the decision into matrix entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.guide import guide_deployable, guide_variant
from utils.symbol_glossary import to_emoji

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


def redundant(entry: Mapping[str, str]) -> bool:
    """Whether the sweep drops this row as coverage an earlier row already has."""
    if entry["priority"] == "true":
        return False
    return entry["clone"] == "true" or entry["covered"] != "0"


def mark(
    entries: list[dict[str, str]],
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> list[dict[str, str]]:
    """Hand one entry per role the replay, and give its label the 📖.

    Only the first entry of the chosen variant: a priority row runs every mode
    and onion state it offers, and replaying the same README block in each of
    them proves nothing the first replay did not. The glyph goes between the
    variant number and the ⭐ of a priority row, with no space between the two:
    they are one marker block, not two axes.

    The row has to run in the guide's own mode. The replay is a second deploy
    on the same runner, so hanging it on a swarm row would ask that runner to
    bring a compose stack up beside a swarm one. Only rows in that mode count
    as deployed here either, so the variant search cannot settle on one that
    this sweep runs in swarm alone.
    """
    star = f" {to_emoji('priority')}"
    deployed: dict[str, set[str]] = {}
    for entry in entries:
        app = entry["apps"]
        if not redundant(entry) and entry["mode"] == guide_deployable(app):
            deployed.setdefault(app, set()).add(entry["variant"])
    marked: set[str] = set()
    for entry in entries:
        app = entry["apps"]
        if app in marked or redundant(entry):
            continue
        variant, mode = guide_variant(app, variants_per_app, deployed.get(app, set()))
        if not mode or entry["variant"] != variant or entry["mode"] != mode:
            continue
        entry["instructions"] = mode
        entry["label"] = (
            entry["label"].removesuffix(star)
            + f" {to_emoji('instructions')}"
            + (to_emoji("priority") if entry["priority"] == "true" else "")
        )
        marked.add(app)
    return entries
