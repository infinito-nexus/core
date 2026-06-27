"""Best-effort install of the distro-packaging lint validators.

``scripts/lint/packages.sh`` validates the generated packaging metadata
with each ecosystem's native parser. This installer provisions those
parsers wherever the platform's package manager can: on Debian (apt) the
lint container gets ``dpkg-parsechangelog`` (``dpkg-dev``), ``rpmspec``
(``rpm``) and ``rpmlint``; on Arch (pacman) a dev host gets ``namcap``.

Every install is best-effort and per-command: cross-distro tools are
often unavailable, and ``scripts/lint/packages.sh`` skips absent ones, so
a failed candidate MUST NOT break the lint bootstrap. The validators are
intentionally kept out of the install stamp's required-tool set so a
non-Debian environment never loops trying to install a tool it cannot.
This group is installed explicitly by the ``lint-packages`` make target
(an explicit group bypasses the stamp), so the commands are provisioned
every run rather than only on the first all-mode install.
"""

from __future__ import annotations

import contextlib

from utils.install.primitives import which
from utils.install.system_pkg import (
    detect_package_manager,
    install_package_candidates,
)

_VALIDATOR_PACKAGES: dict[str, dict[str, list[str]]] = {
    "dpkg-parsechangelog": {"apt-get": ["dpkg-dev"], "pacman": ["dpkg"]},
    "rpmspec": {"apt-get": ["rpm"], "dnf": ["rpm-build"], "yum": ["rpm-build"]},
    "rpmlint": {"apt-get": ["rpmlint"], "dnf": ["rpmlint"], "pacman": ["rpmlint"]},
    "namcap": {"pacman": ["namcap"]},
}


def ensure() -> None:
    manager: str | None = None
    with contextlib.suppress(Exception):
        manager = detect_package_manager()
    if manager is None:
        return

    for command, by_manager in _VALIDATOR_PACKAGES.items():
        candidates = by_manager.get(manager)
        if not candidates or which(command):
            continue
        with contextlib.suppress(Exception):
            install_package_candidates(manager, candidates)
