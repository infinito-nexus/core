"""Repository-side access to the vulnerability pipeline of ``sys-ctl-hlth-runtime``.

The role ships the pipeline as one standalone script, since a node runs it
without the repository. The repository tools load that same file instead of
keeping a second copy of the parsers, the threshold and the suppression
matching.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import sys
from typing import TYPE_CHECKING, Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.security.engine import ROLE

if TYPE_CHECKING:
    from types import ModuleType

SCRIPT = PROJECT_ROOT / "roles" / ROLE / "files" / "python" / "script.py"
MODULE = "sys_ctl_hlth_runtime_script"


@functools.cache
def pipeline() -> ModuleType:
    """Return the role's ``script.py`` loaded as a module."""
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE] = module
    spec.loader.exec_module(module)
    return module


def role_services() -> dict[str, Any]:
    """Return the role's ``meta/services.yml`` as declared."""
    return load_yaml_any(str(PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_SERVICES))


def user_runtime() -> tuple[str, ...]:
    """Return ``docker run`` as the calling user, so the engines write files it owns."""
    return ("docker", "run", "--user", f"{os.getuid()}:{os.getgid()}")


def engine_image(engine: str) -> str:
    """Return the pinned ``<image>:<version>`` of one engine."""
    service = role_services()[engine]
    return f"{service['image']}:{service['version']}"
