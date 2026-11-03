"""Read the host-state probes of the constructor pre-flight."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def disk_usage_errors(paths: Sequence[str], df_output: str, maximum: int) -> list[str]:
    """Every probed path whose filesystem is fuller than the limit.

    Args:
        paths: the paths ``df -P`` was asked about, in the order it got them.
        df_output: the stdout of ``df -P -- <paths>``, header included.
        maximum: the highest usage in percent a filesystem may reach.

    Returns:
        One message per path whose filesystem uses more than ``maximum``
        percent; empty when every filesystem stays at or below it.

    Raises:
        ValueError: the output holds another number of rows than paths, or a
            row carries no usage percentage.
    """
    rows = [line for line in df_output.splitlines()[1:] if line.strip()]
    if len(rows) != len(paths):
        raise ValueError(
            f"df reported {len(rows)} filesystems for {len(paths)} paths: {df_output!r}"
        )
    errors: list[str] = []
    for path, row in zip(paths, rows, strict=True):
        fields = row.split(None, 5)
        if len(fields) != 6 or not fields[4].rstrip("%").isdigit():
            raise ValueError(f"df row without a usage percentage: {row!r}")
        usage = int(fields[4].rstrip("%"))
        if usage > maximum:
            errors.append(
                f"{path} lies on {fields[5]}, which is {usage} % full (limit {maximum} %)"
            )
    return errors
