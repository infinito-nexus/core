"""A roles tree with one host-mode-only backup provider and three hosts.

``web-app-light`` and ``web-app-bulky`` embed the provider; variant 0 of
``web-app-bulky`` also pulls the 50 GB ``svc-ai-heavy``, variant 1 switches it
off. ``web-app-plain`` embeds nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from pathlib import Path

SWARM = "  modes:\n    swarm:\n      enabled: true\n"
BACKUP = "container_backup:\n  enabled: true\n  shared: true\n"

SERVICES = {
    "svc-bkp-vault": (
        "vault:\n  modes:\n    host:\n      enabled: true\n    swarm:\n"
        "      enabled: false\n  enabled: true\n  shared: true\n"
        "  provides: container_backup\n  min_storage: 0GB\n"
    ),
    "svc-ai-heavy": f"heavy:\n{SWARM}  enabled: true\n  shared: true\n  min_storage: 50GB\n",
    "web-app-light": f"light:\n{SWARM}  enabled: true\n  min_storage: 1GB\n{BACKUP}",
    "web-app-bulky": (
        f"bulky:\n{SWARM}  enabled: true\n  min_storage: 2GB\n{BACKUP}"
        "heavy:\n  enabled: true\n  shared: true\n"
    ),
    "web-app-plain": f"plain:\n{SWARM}  enabled: true\n  min_storage: 500MB\n",
}

VARIANTS = {
    "web-app-bulky": "- {}\n- services:\n    heavy:\n      enabled: false\n      shared: false\n",
}

APPS = frozenset(SERVICES)


def build_role(roles_dir: Path, role: str, services: str) -> None:
    """Write one application role with the given meta/services.yml text."""
    role_dir = roles_dir / role
    (role_dir / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True, exist_ok=True)
    (role_dir / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True, exist_ok=True)
    (role_dir / ROLE_FILE_VARS_MAIN).write_text(
        f"application_id: {role}\n", encoding="utf-8"
    )
    (role_dir / ROLE_FILE_META_SERVICES).write_text(services, encoding="utf-8")


def build(roles_dir: Path) -> None:
    """Write the fixture roles under roles_dir."""
    for role, services in SERVICES.items():
        build_role(roles_dir, role, services)
        if role in VARIANTS:
            (roles_dir / role / ROLE_FILE_META_VARIANTS).write_text(
                VARIANTS[role], encoding="utf-8"
            )
