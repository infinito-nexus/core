from __future__ import annotations

from dataclasses import dataclass

HOST_EXECUTED = "executed"
HOST_SKIPPED = "skipped"
HOST_FAILED = "failed"


@dataclass(frozen=True)
class RoleRuntime:
    """One role's measured runtime within a deploy segment.

    For a non-matrix (combined) deploy with no round markers, the segment
    fields are empty strings. ``hosts`` serializes the per-host outcome of
    the role's tasks as space-separated ``host=status`` pairs (status:
    executed | skipped | failed); empty when the log carries no per-host
    task results for the role (e.g. module aggregate rows).
    """

    role: str
    seconds: float
    round: str = ""
    rounds_total: str = ""
    pass_num: str = ""
    pass_mode: str = ""
    hosts: str = ""

    @property
    def host_map(self) -> dict[str, str]:
        return dict(pair.split("=", 1) for pair in self.hosts.split() if "=" in pair)

    @property
    def segmented(self) -> bool:
        return bool(self.round)

    @property
    def segment_label(self) -> str:
        if not self.segmented:
            return "All roles"
        return (
            f"Round {self.round}/{self.rounds_total} · "
            f"PASS {self.pass_num} ({self.pass_mode})"
        )
