from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import read_text

if TYPE_CHECKING:
    from pathlib import Path

DOCKERFILE = PROJECT_ROOT / "Dockerfile"

_STAGE = re.compile(r"^FROM\s+\S+\s+AS\s+(?P<name>\S+)$", re.IGNORECASE)
_COPY = re.compile(r"^COPY\s+(?P<source>\S+)\s+\$\{INFINITO_SRC_DIR\}/(?P<target>\S+)$")


def _instructions() -> list[tuple[str, str]]:
    stage = ""
    found: list[tuple[str, str]] = []
    pending = ""
    for raw in read_text(str(DOCKERFILE)).splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        pending = f"{pending} {line}" if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        start = _STAGE.match(pending)
        if start:
            stage = start.group("name")
        else:
            found.append((stage, pending))
        pending = ""
    return found


def stage_runs(stage: str) -> list[str]:
    return [
        text
        for name, text in _instructions()
        if name == stage and text.startswith("RUN ")
    ]


def materialise(destination: Path, stages: frozenset[str]) -> None:
    for stage, text in _instructions():
        match = _COPY.match(text)
        if stage not in stages or not match:
            continue
        source = PROJECT_ROOT / match.group("source")
        target = destination / match.group("target")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
