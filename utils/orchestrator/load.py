"""The load conditions of the cron entries, from measured figures.

The orchestrator samples the host and the translation lane and passes the
figures here; ``conditions`` returns the condition names ``cron.due`` reads as
``conditions_met``, and ``lane_action`` folds the entries that fired at one
tick into the one action the lane takes. The day rule judges the rest of the
system, the host minus the lane, so the lane's own load never pauses it.
"""

from __future__ import annotations

from dataclasses import dataclass

START_BELOW_PERCENT = 30.0
PAUSE_ABOVE_PERCENT = 95.0
LOAD_BELOW = "host-load-below-30"
LOAD_ABOVE = "host-load-above-95"
PAUSE = "pause"
START = "start"


@dataclass(frozen=True)
class Load:
    """One CPU and GPU sample.

    Args:
        cpu: CPU use as a share of the host's whole capacity, in percent.
        gpu: GPU use as a share of the host's whole capacity, in percent.
    """

    cpu: float
    gpu: float


def rest_of_system(host: Load, lane: Load) -> Load:
    """Return the load of everything on the host except the lane.

    Args:
        host: the whole host's sample.
        lane: the translation lane's own sample, taken at the same tick.
    """
    return Load(max(host.cpu - lane.cpu, 0.0), max(host.gpu - lane.gpu, 0.0))


def conditions(host: Load, lane: Load, *, accelerated: bool) -> frozenset[str]:
    """Return the load conditions that hold for the rest of the system.

    ``host-load-below-30`` holds when CPU and GPU are both below 30 %, and
    ``host-load-above-95`` when CPU or GPU is above 95 %. On a host without a
    usable GPU the GPU half of the start condition counts as met and the GPU
    half of the pause condition never holds.

    Args:
        host: the whole host's sample.
        lane: the translation lane's own sample, taken at the same tick.
        accelerated: whether the host hands a GPU to the lane, as
            ``utils.i18n.libretranslate.accelerated`` reports it.
    """
    rest = rest_of_system(host, lane)
    gpu_idle = not accelerated or rest.gpu < START_BELOW_PERCENT
    gpu_busy = accelerated and rest.gpu > PAUSE_ABOVE_PERCENT
    met = set()
    if rest.cpu < START_BELOW_PERCENT and gpu_idle:
        met.add(LOAD_BELOW)
    if rest.cpu > PAUSE_ABOVE_PERCENT or gpu_busy:
        met.add(LOAD_ABOVE)
    return frozenset(met)


def lane_action(fired: list[dict]) -> str | None:
    """Return the one action the lane takes for the entries fired at a tick.

    A ``pause`` outranks a ``start`` of the same tick, so the 07:00 end of the
    night window pauses the lane even where the day rule's first tick would
    start it, and the day rule takes over from its next tick.

    Args:
        fired: the entries ``cron.due`` returned for the tick.
    """
    actions = {entry.get("action") for entry in fired}
    if PAUSE in actions:
        return PAUSE
    if START in actions:
        return START
    return None
