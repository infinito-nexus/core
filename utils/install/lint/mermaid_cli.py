"""Install @mermaid-js/mermaid-cli (mmdc) and the chrome-headless-shell it renders with.

mmdc comes from npm with ``PUPPETEER_SKIP_DOWNLOAD`` set; the browser is
provisioned afterwards through the puppeteer that npm installed next to mmdc,
at the revision its puppeteer-core pins, as root with its shared libraries
(``--install-deps``). ``unzip`` is ensured first because puppeteer extracts the
browser with it. A failed install warns instead of aborting ``install-lint``, so
sandboxes without npm or browser access still get the rest of the lint
toolchain.
"""

from __future__ import annotations

import contextlib
import os
import re
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


def _mmdc_puppeteer() -> Path | None:
    mmdc = shutil.which("mmdc")
    if mmdc is None:
        return None
    for parent in Path(mmdc).resolve().parents:
        puppeteer = parent / "node_modules" / "puppeteer"
        if puppeteer.is_dir():
            return puppeteer
    return None


def _puppeteer_core(puppeteer: Path) -> Path | None:
    for base in (puppeteer, *puppeteer.parents):
        if base.name == "node_modules":
            continue
        core = base / "node_modules" / "puppeteer-core"
        if core.is_dir():
            return core
    return None


def browser_revision() -> str | None:
    puppeteer = _mmdc_puppeteer()
    if puppeteer is None:
        return None
    core = _puppeteer_core(puppeteer)
    if core is None:
        return None
    revisions = core / "lib" / "puppeteer" / "revisions.js"
    try:
        text = revisions.read_text(encoding="utf-8")  # nocheck: cache-read  npm prefix
    except OSError:
        return None
    match = re.search(rf"'{BROWSER}':\s*'([^']+)'", text)
    return match.group(1) if match else None


def browser_installed() -> bool:
    revision = browser_revision()
    if revision is None:
        return False
    return any(
        path.is_file() for path in browser_cache().glob(f"*-{revision}/*/{BROWSER}")
    )


def _provision_browser(puppeteer: Path) -> subprocess.CompletedProcess[str]:
    argv = [
        str(puppeteer.parent / ".bin" / "puppeteer"),
        "browsers",
        "install",
        BROWSER,
    ]
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
    puppeteer = _mmdc_puppeteer()
    if puppeteer is None:
        warn(f"{BROWSER} provisioning skipped: no puppeteer next to mmdc")
        return
    log(f"Provisioning {BROWSER} for mmdc via its own puppeteer.")
    try:
        done = _provision_browser(puppeteer)
        if done.returncode != 0:
            revision = browser_revision()
            if revision is not None:
                for partial in browser_cache().glob(f"*-{revision}"):
                    shutil.rmtree(partial, ignore_errors=True)
            done = _provision_browser(puppeteer)
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
