from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleRuntime:
    """One role's measured runtime within a deploy segment.

    For a non-matrix (combined) deploy with no round markers, the segment
    fields are empty strings.
    """

    role: str
    seconds: float
    round: str = ""
    rounds_total: str = ""
    pass_num: str = ""
    pass_mode: str = ""

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
