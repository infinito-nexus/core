"""Install @mermaid-js/mermaid-cli (mmdc) via npm global.

Best-effort: the puppeteer browser is not downloaded here
(``PUPPETEER_SKIP_DOWNLOAD``) so ``install-lint`` stays sandbox-safe. mmdc only
needs a browser to RENDER, which ``scripts/lint/mermaid.sh`` provisions on demand
(``npx puppeteer browsers install chrome-headless-shell``) right before it
renders. That browser ships as a zip, so ``unzip`` is ensured here (puppeteer's
extractor needs it, else it leaves an empty version dir and mmdc reports the
browser missing). A failed install warns instead of aborting ``install-lint``,
so sandboxes without npm/browser access still get the rest of the lint toolchain.
"""

from __future__ import annotations

import contextlib
import os

from utils.install.npm import npm_install_global
from utils.install.primitives import log, warn, which
from utils.install.system_pkg import install_command_via_pkg


def _ensure_unzip() -> None:
    if which("unzip"):
        return
    with contextlib.suppress(Exception):
        install_command_via_pkg("unzip")


def ensure() -> None:
    _ensure_unzip()
    if which("mmdc"):
        return
    log("Missing command 'mmdc'. Installing @mermaid-js/mermaid-cli via npm.")
    os.environ["PUPPETEER_SKIP_DOWNLOAD"] = "1"
    try:
        npm_install_global("@mermaid-js/mermaid-cli")
    except Exception as exc:  # noqa: BLE001 - best-effort optional lint tool
        warn(f"mermaid-cli install skipped (optional lint tool): {exc}")
        return
    if not which("mmdc"):
        warn("Command 'mmdc' is still unavailable after installation.")
