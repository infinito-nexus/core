"""Detect the host distro and self-install the binaries the diagnose probes need."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from cli.contributing.network.diagnose.config import INSTALL_CMDS, TOOLS
from cli.contributing.network.diagnose.format import cmd_capture


def detect_distro_id(*, os_release_path: str = "/etc/os-release") -> str:
    """Return the distro id from /etc/os-release, lowercased; empty string when unreadable."""
    try:
        text = Path(os_release_path).read_text()  # nocheck: cache-read
        for raw in text.splitlines():
            if raw.startswith("ID="):
                return raw.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass  # best-effort: return empty distro id when /etc/os-release is unreadable
    return ""


def missing_tools() -> list[str]:
    return [t for t in TOOLS if shutil.which(t) is None]


def ensure_tools() -> None:
    """Install the missing TOOLS via the distro's package manager, when possible."""
    missing = missing_tools()
    if not missing:
        return

    distro = detect_distro_id()
    cmd = INSTALL_CMDS.get(distro)
    if cmd is None:
        print(
            f"  [tool-install] missing {missing} but distro={distro or '?'} unsupported; skipping",
            file=sys.stderr,
        )
        return

    if distro in ("debian", "ubuntu"):
        rc_upd, _ = cmd_capture(
            ["apt-get", "update", "-o", "DPkg::Lock::Timeout=120"], timeout=180.0
        )
        if rc_upd != 0:
            print(
                f"  [tool-install] apt-get update rc={rc_upd}; trying install anyway",
                file=sys.stderr,
            )

    if os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo", *cmd]

    print(
        f"  [tool-install] installing {' '.join(cmd[-2:])} via {distro}",
        file=sys.stderr,
    )
    rc, out = cmd_capture(cmd, timeout=180.0)
    if rc != 0:
        print(f"  [tool-install] FAILED rc={rc}: {out.strip()[:200]}", file=sys.stderr)
