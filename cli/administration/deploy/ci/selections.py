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


def deployed_selections(jobs: list[dict]) -> set[str]:
    """Every selection the source run actually deployed, green or red.

    The verdict is irrelevant here: what matters is that the run reached the
    row at all, because that is what a retrigger no longer has to repeat.
    """
    return {
        selection.describe(
            selection.Pin(
                app,
                tuple(int(part) for part in label.variant.split(",") if part),
                label.mode,
                label.tor,
                label.distro or None,
            )
        )
        for app, _mode, job in _iter_deploy_jobs(jobs)
        if (label := axes.parse_label(str(job.get("name", "")))) is not None
    }


def settled_selections(jobs: list[dict]) -> set[str]:
    """Every selection the source run reached a verdict on.

    Narrower than :func:`deployed_selections`, which counts a row the run
    merely started. A cancelled row, or one still running when the run was
    read, was never given the chance to be green or red, so treating it as
    covered retires a combination nobody judged.

    Only ``success`` and ``failure`` settle anything. Everything else, the
    aborts and the still-running, is owed another attempt at the same
    combination.
    """
    return {
        selection.describe(
            selection.Pin(
                app,
                tuple(int(part) for part in label.variant.split(",") if part),
                label.mode,
                label.tor,
                label.distro or None,
            )
        )
        for app, _mode, job in _iter_deploy_jobs(jobs)
        if _effective(job) in {"success", "failure"}
        and (label := axes.parse_label(str(job.get("name", "")))) is not None
    }


def row_selection(entry: Mapping[str, Any]) -> str:
    """One matrix row as the token that reproduces it.

    Args:
        entry: a row of :func:`cli.meta.ci.matrix.entries_of`.
    """
    return selection.describe(
        selection.Pin(
            entry["apps"],
            tuple(
                int(part) for part in str(entry.get("variant", "")).split(",") if part
            ),
            entry["mode"],
            entry["tor"] == "true",
            entry["distro"],
        )
    )


def _row_identity(pin: selection.Pin) -> str:
    """The part of a selection that survives the sweep rotation."""
    return selection.describe(selection.Pin(pin.app, pin.variants))


def unrun_selections(regular: list[dict[str, str]], deployed: set[str]) -> list[str]:
    """The rows of the ranking the source run holds no job for.

    A row that never ran has no verdict, and the retrigger reaches it only if
    it survives the budget a second time. Naming it on the priority line is
    what puts it in front of the rows that already have one.

    Membership is decided on ``role#variant`` alone. Mode, onion state and
    distro are assigned by the rotation and differ between the source run's
    sweep and the one this ranking was computed under, so comparing full
    tokens reports almost every row as unrun. Each row is a distinct
    ``role#variant``, which makes it the identity to compare on.

    The returned token keeps the axes anyway, unlike :func:`resume_offset`,
    which names a place in the ranking and must stay axis-free. Here they are
    the retrigger's own assignment for a row that was never attempted, and a
    priority entry that names axes keeps them.

    Args:
        regular: the regular line of the retrigger's own discovery, in ranking
            order.
        deployed: tokens the source run deployed (:func:`deployed_selections`).

    Returns:
        sorted, deduplicated tokens for the rows with no job in the source run.
    """
    ran = {_row_identity(selection.parse(token)) for token in deployed}
    return sorted(
        {
            row_selection(entry)
            for entry in regular
            if _row_identity(selection.parse(row_selection(entry))) not in ran
        }
    )


def resume_offset(regular: list[dict[str, str]], deployed: set[str]) -> str:
    """Where a retrigger should pick the regular line up again.

    The source run deployed a window of the ranking and stopped at its budget.
    Everything inside that window has a verdict -- the red rows come back on
    the priority line anyway -- so the regular line has no reason to walk it a
    second time. The answer is the last row of the leading run of deployed
    rows, as a selection token: a token still names the same row after the
    ranking shifts, a row count does not.

    Stops at the first gap. A hole inside the window means that row was
    filtered out, not that the run got further, and resuming past it would skip
    whatever follows.

    Args:
        regular: the regular line of the retrigger's own discovery, in ranking
            order.
        deployed: tokens the source run deployed (:func:`deployed_selections`).

    Returns:
        the ``role#variant`` token to resume at, or ``''`` when the source run
        deployed nothing of this line -- then the retrigger starts at the head,
        as it would without an offset.

        The returned token names a place in the ranking, so it carries no axes.
        Membership is still tested on the full deploy token, because that is
        what the source run recorded; but every axis rotates with the sweep
        number, and the retrigger gets a fresh one. An axis-pinned offset would
        therefore resolve only in the rare sweep whose rotation happens to
        reproduce the source run's combination, and abort the discovery of
        every chunk in all the others.
    """
    resume = ""
    for entry in regular:
        if row_selection(entry) not in deployed:
            break
        variants = tuple(
            int(part) for part in str(entry.get("variant", "")).split(",") if part
        )
        resume = selection.describe(selection.Pin(entry["apps"], variants))
    return resume
