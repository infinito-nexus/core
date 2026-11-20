from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DockerImageVersionEntry:
    role: str
    service: str
    image: str
    version: str
    config_path: Path
    hold: str = ""


@dataclass(frozen=True)
class DockerImageVersionUpdate:
    entry: DockerImageVersionEntry
    latest: str
