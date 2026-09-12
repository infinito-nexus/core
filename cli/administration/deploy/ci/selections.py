"""Turn a run's deploy jobs back into selection tokens.

A deploy job title carries the whole row it deployed -- role, variant, mode,
onion state, distro, filesystem -- and :mod:`utils.github.variant.selection`
is the grammar that writes it back down.

The filesystem is the one axis a token built here leaves out. The title states
the kind the matrix *assigned*, which a deploy is allowed to fall back from
when the host cannot serve it, so the title does not prove what the job ran on.
Writing it into a token would also state it as named by a human, which makes it
binding (:func:`utils.github.variant.axes.assign`): a retrigger would then fail
on the very condition the fallback exists to absorb. The retrigger lets the
rotation assign it again and reports what it got. Reading the tokens out of a finished run is what lets a
retrigger replay exactly what failed and start the regular line where that run
stopped, instead of aggregating to role ids and guessing the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.github.variant import axes, selection

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import Any

from .runs import _effective, _iter_deploy_jobs


def failed_selections(jobs: list[dict], *, strict: bool = False) -> list[str]:
    """The selection tokens that reproduce exactly what did not pass.

    A role aggregated to its id loses what actually broke: the retrigger then
    redeploys every variant of it, in whatever mode and onion state the sweep
    rotation happens to pick, and the combination that failed may not be among
    them. Each failed job therefore contributes its own
    ``role#variant@mode+tor`` token (:mod:`utils.github.variant.selection`), so
    the priority line replays that job and nothing else.

    Every mode is read; there is no scope to narrow to. A run that failed in
    swarm and in compose comes back as two tokens for the same role.

    Args:
        jobs: the source run's jobs.
        strict: only hard failures (❌) count; cancelled, timed out and still
            running are left out.

    Returns:
        sorted, deduplicated tokens.
    """
    tokens = set()
    for app, _mode, job in _iter_deploy_jobs(jobs):
        state = _effective(job)
        if state == "success" or (strict and state != "failure"):
            continue
        label = axes.parse_label(str(job.get("name", "")))
        tokens.add(
            selection.describe(
                selection.Pin(
                    app,
                    tuple(int(part) for part in label.variant.split(",") if part),
                    label.mode,
                    label.tor,
                    label.distro or None,
                )
            )
        )
    return sorted(tokens)


def collapse_to_roles(tokens: Iterable[str]) -> list[str]:
    """The same selections with every axis dropped, one entry per role.

    :func:`failed_selections` reproduces the combination that broke, which is
    what a handful of red rows deserves. Once most of the ranking is red the
    question is no longer which combination broke but whether the role comes up
    at all, and a token per combination spends the priority budget proving the
    same role red twice. The role name lets the rotation pick the axes.

    What this gives up is the guarantee the pinned form exists for: the
    combination that failed may not be among the ones the retrigger draws.

    Args:
        tokens: selection tokens, as :func:`failed_selections` returns them.

    Returns:
        sorted, deduplicated role ids.
    """
    return sorted({selection.parse(token).app for token in tokens})


def _variants(entry: Mapping[str, Any]) -> tuple[int, ...]:
    """The variant shards one matrix row covers."""
    return tuple(int(part) for part in str(entry.get("variant", "")).split(",") if part)


def row_identity(entry: Mapping[str, Any]) -> str:
    """One matrix row as the ``role#variant`` the sweep rotation cannot move.

    Args:
        entry: a row of :func:`cli.meta.ci.matrix.entries_of`.
    """
    return selection.describe(selection.Pin(entry["apps"], _variants(entry)))


def proven_rows(jobs: list[dict]) -> set[str]:
    """The rows the source run proved, as ``role#variant``, axes dropped.

    Mode, onion state, distro and filesystem are assigned by the rotation over
    the sweep number, and a retrigger is a new run with a new number
    (``call-orchestrator.yml`` falls back to ``github.run_number``). Comparing
    the full deploy tokens therefore compares two different sweeps: measured
    against the current ranking, 2 of 277 rows matched, so every walk stopped
    on its first row and the regular line never left the head. The row is the
    coarsest identity the rotation cannot move.

    Dropping the axes does not mean forgiving them. A row is proven only when
    *every* job it had was green: one red or aborted combination un-proves it,
    however many green siblings it has. Only a priority row can have several,
    since it deploys its whole cross-product at once while a regular row gets
    one combination per sweep -- and letting a green compose job carry a red
    swarm one would walk the regular line past a combination nobody fixed.

    Args:
        jobs: the source run's jobs.
    """
    green: set[str] = set()
    broken: set[str] = set()
    for app, _mode, job in _iter_deploy_jobs(jobs):
        label = axes.parse_label(str(job.get("name", "")))
        if label is None:
            continue
        row = selection.describe(
            selection.Pin(
                app, tuple(int(part) for part in label.variant.split(",") if part)
            )
        )
        (green if _effective(job) == "success" else broken).add(row)
    return green - broken


def carried_index(regular: list[dict[str, str]], carried: str, proven: set[str]) -> int:
    """Where in *regular* the source run began reading.

    A retrigger inherits the window its source was given: the rows in front of
    that window were proven by the runs before it, and re-walking them from the
    head would redeploy a green stretch that nobody doubts. The source run's
    own ``offset`` input is that window's start.

    The token can name a row this ranking no longer has -- the role was
    removed, a variant was dropped, the filters moved. The start is then the
    first row the source run got green, which lies inside the same window and
    so never falls behind it. A run with nothing green and an unresolvable
    token leaves no anchor at all and starts at the head.

    Args:
        regular: the regular line of the retrigger's own discovery, in ranking
            order.
        carried: the source run's ``offset`` input, a token or a row count.
        proven: the rows the source run got green (:func:`proven_rows`).

    Returns:
        the index to start reading at; ``0`` when the source run was given no
        offset.
    """
    if not carried:
        return 0
    if carried.lstrip("+-").isdigit():
        return max(int(carried), 0)
    pin = selection.parse(carried)
    for index, entry in enumerate(regular):
        if selection.covers(pin, entry):
            return index
    for index, entry in enumerate(regular):
        if row_identity(entry) in proven:
            return index
    return 0


def resume_offset(
    regular: list[dict[str, str]],
    proven: set[str],
    leading: Iterable[selection.Pin] = (),
    carried: str = "",
) -> str:
    """Where a retrigger should pick the regular line up again.

    The source run read a window of the ranking, starting where *carried* put
    it (:func:`carried_index`) and stopping at its budget. Only the green part
    of that window is newly settled, so the answer is the last row of the
    leading run of *successful* rows behind the window's start, as a selection
    token -- a token still names the same row after the ranking shifts, a row
    count does not.

    The window's start is the floor: with nothing green behind it the answer is
    the start itself, never the head. Walking back to the head is what made
    every retrigger redeploy the whole stretch its predecessors had already
    proven.

    Stops at the first row that is not proven, whether or not the priority line
    claims it, and one red combination is enough to un-prove a row
    (:func:`proven_rows`). Resuming past it would drop every other combination
    of that row and everything the run never reached behind it.

    A row the priority line claims is never the answer. ``regular`` is
    discovered without the priority line (see the retrigger's ``_ranking``), so
    it still holds rows the run will hand to that line instead
    (:func:`cli.meta.ci.matrix.candidates`): a variant-less pin takes its whole
    role, a pinned one takes those variants. Naming such a row would emit an
    offset that resolves against nothing once the run applies the priority
    line, and abort the discovery of every chunk.

    Args:
        regular: the regular line of the retrigger's own discovery, in ranking
            order.
        proven: the rows the source run got green in every combination it ran
            them in (:func:`proven_rows`).
        leading: the retrigger's priority pins, whose rows leave the regular
            line.
        carried: the source run's own ``offset`` input.

    Returns:
        the ``role#variant`` token to resume at, or ``''`` when the source run
        started at the head and got nothing skippable of this line green --
        then the retrigger starts at the head too, as it would without an
        offset.

        The returned token names a place in the ranking, so it carries no axes,
        and neither does the membership test behind it (:func:`proven_rows`):
        the source run recorded its combinations under its own sweep number and
        the retrigger gets a fresh one, so comparing them row by row is the only
        comparison that survives the rotation.
    """
    pins = tuple(leading)
    claimed_apps = {pin.app for pin in pins if not pin.variants}
    claimed_rows = {(pin.app, variant) for pin in pins for variant in pin.variants}

    def free(entry: Mapping[str, Any]) -> str:
        app = entry["apps"]
        variants = _variants(entry)
        if app in claimed_apps or any((app, v) in claimed_rows for v in variants):
            return ""
        return row_identity(entry)

    start = carried_index(regular, carried, proven)
    window = regular[start:]
    resume = next((token for entry in window if (token := free(entry))), "")
    if not start:
        resume = ""
    for entry in window:
        if row_identity(entry) not in proven:
            break
        resume = free(entry) or resume
    return resume
