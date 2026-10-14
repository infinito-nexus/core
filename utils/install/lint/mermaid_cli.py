"""Install @mermaid-js/mermaid-cli (mmdc) and the chrome-headless-shell it renders with.

mmdc comes from npm with ``PUPPETEER_SKIP_DOWNLOAD`` set; the browser is
provisioned through puppeteer afterwards, as root with its shared libraries
(``--install-deps``). ``unzip`` is ensured first because puppeteer extracts the
browser with it. A failed install warns instead of aborting ``install-lint``, so
sandboxes without npm or browser access still get the rest of the lint
toolchain.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

from utils.install.npm import npm_install_global
from utils.install.primitives import log, warn, which
from utils.install.system_pkg import install_command_via_pkg

BROWSER = "chrome-headless-shell"
PROVISION_TIMEOUT_S = 900


def _ensure_unzip() -> None:
    if which("unzip"):
        return
    with contextlib.suppress(Exception):
        install_command_via_pkg("unzip")


def browser_cache() -> Path:
    base = os.environ.get("PUPPETEER_CACHE_DIR") or Path.home() / ".cache" / "puppeteer"
    return Path(base) / BROWSER


def browser_installed() -> bool:
    return any(path.is_file() for path in browser_cache().glob(f"*/*/{BROWSER}"))


def _provision_browser() -> subprocess.CompletedProcess[str]:
    argv = ["npx", "--yes", "puppeteer", "browsers", "install", BROWSER]
    if os.geteuid() == 0:
        argv.append("--install-deps")
    env = {k: v for k, v in os.environ.items() if k != "PUPPETEER_SKIP_DOWNLOAD"}
    return subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        timeout=PROVISION_TIMEOUT_S,
        check=False,
    )


def _ensure_browser() -> None:
    if browser_installed():
        return
    log(f"Provisioning {BROWSER} for mmdc via puppeteer.")
    try:
        done = _provision_browser()
        if done.returncode != 0:
            shutil.rmtree(browser_cache(), ignore_errors=True)
            done = _provision_browser()
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn(f"{BROWSER} provisioning skipped (optional lint tool): {exc}")
        return
    if done.returncode != 0:
        warn(
            f"{BROWSER} provisioning failed (optional lint tool):\n"
            f"{done.stdout}{done.stderr}"
        )


def ensure() -> None:
    _ensure_unzip()
    if not which("mmdc"):
        log("Missing command 'mmdc'. Installing @mermaid-js/mermaid-cli via npm.")
        os.environ["PUPPETEER_SKIP_DOWNLOAD"] = "1"
        try:
            npm_install_global("@mermaid-js/mermaid-cli")
        except Exception as exc:  # noqa: BLE001 - best-effort optional lint tool
            warn(f"mermaid-cli install skipped (optional lint tool): {exc}")
            return
        if not which("mmdc"):
            warn("Command 'mmdc' is still unavailable after installation.")
            return
    _ensure_browser()
