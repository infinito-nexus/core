from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .csvio import read_csv
from .github import records_from_job_url
from .logparse import parse_log

if TYPE_CHECKING:
    from .model import RoleRuntime


def load_records(source: str) -> list[RoleRuntime]:
    """Load runtime records from a URL, a CSV path, or an Ansible log path."""
    if source.startswith(("http://", "https://")):
        return records_from_job_url(source)
    if Path(source).suffix == ".csv":
        return read_csv(source)
    return parse_log(source)
