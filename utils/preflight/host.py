"""Read the host-state probes of the constructor pre-flight."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def disk_usage_errors(
    paths: Sequence[str], df_output: str, maximum: int, minimum_free_gb: int
) -> list[str]:
    """Every probed path whose filesystem is fuller than the limits.

    Args:
        paths: the paths ``df -P`` was asked about, in the order it got them.
        df_output: the stdout of ``df -P -- <paths>``, header included.
        maximum: the usage in percent above which a filesystem counts as full.
        minimum_free_gb: the free space in GB (10^9 bytes) a filesystem above
            ``maximum`` must still offer to pass.

    Returns:
        One message per path whose filesystem uses more than ``maximum``
        percent and offers less than ``minimum_free_gb``; empty otherwise.

    Raises:
        ValueError: the output holds another number of rows than paths, or a
            row carries no usage percentage or no available block count.
    """
    rows = [line for line in df_output.splitlines()[1:] if line.strip()]
    if len(rows) != len(paths):
        raise ValueError(
            f"df reported {len(rows)} filesystems for {len(paths)} paths: {df_output!r}"
        )
    errors: list[str] = []
    for path, row in zip(paths, rows, strict=True):
        fields = row.split(None, 5)
        if (
            len(fields) != 6
            or not fields[4].rstrip("%").isdigit()
            or not fields[3].isdigit()
        ):
            raise ValueError(
                f"df row without a usage percentage or free space: {row!r}"
            )
        usage = int(fields[4].rstrip("%"))
        free_gb = int(fields[3]) * 1024 / 10**9
        if usage > maximum and free_gb < minimum_free_gb:
            errors.append(
                f"{path} lies on {fields[5]}, which is {usage} % full with "
                f"{free_gb:.1f} GB free (limits {maximum} % and {minimum_free_gb} GB)"
            )
    return errors
