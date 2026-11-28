from __future__ import annotations

from pathlib import PurePosixPath

from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

SPEC_FILE = (
    PurePosixPath(ROLE_FILE_PLAYWRIGHT_SPEC).with_name("test-design.js").as_posix()
)
UI_PREFIXES: tuple[str, ...] = ("web-app-", "web-svc-")
DESIGN_ENTITY = "design"
