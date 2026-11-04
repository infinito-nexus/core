"""Reduce the platforms a role's images publish to where the role can run.

A role is schedulable only where *every* image it pins can run, so its
capability is the intersection over its services rather than a property of
any one of them. Kept apart from the registry probe so the reduction can be
tested without a network.
"""

from __future__ import annotations

from utils.github.variant.pools import ARCHITECTURES

LINUX = "linux"


def runnable_architectures(platforms) -> set[str]:
    """Return the matrix architectures *platforms* can be scheduled on.

    Args:
        platforms: ``os/architecture`` strings as a registry reports them.

    Returns:
        The subset of :data:`ARCHITECTURES` offered for ``linux``. Anything
        else a manifest lists - another operating system, an architecture the
        matrix does not rotate - is dropped, because it cannot carry a row.
    """
    offered = set()
    for entry in platforms or ():
        os_name, _, architecture = str(entry).partition("/")
        if os_name == LINUX and architecture in ARCHITECTURES:
            offered.add(architecture)
    return offered


def role_capability(
    offered,
) -> tuple[set[str] | None, dict[str, list[str]], list[str]]:
    """Intersect what a role's images publish, and name what each one lacks.

    Args:
        offered: mapping of image label to its ``os/architecture`` set, or to
            ``None`` for an image whose registry answer was indeterminate.

    Returns:
        ``(capability, blame, unread)``. ``capability`` is the intersection
        over the images that answered, or ``None`` when none did - which a
        caller must not read as "runs nowhere", since a throttled sweep
        produces it. ``blame`` maps an architecture to the labels that cannot
        run it, so a failure names the pin to change rather than only the
        role. ``unread`` lists the labels that did not answer.

    An incomplete read can only ever overstate the capability, because the
    intersection skips what it could not see. A caller may therefore trust
    ``capability`` to decide an architecture is missing, but must not conclude
    from it that a narrowing is unnecessary while ``unread`` is non-empty: the
    image it could not read may be the one the narrowing exists for.
    """
    capability: set[str] | None = None
    blame: dict[str, list[str]] = {}
    unread: list[str] = []
    for label in sorted(offered):
        platforms = offered[label]
        if platforms is None:
            unread.append(label)
            continue
        runnable = runnable_architectures(platforms)
        for architecture in sorted(set(ARCHITECTURES) - runnable):
            blame.setdefault(architecture, []).append(label)
        capability = runnable if capability is None else capability & runnable
    return capability, blame, unread
