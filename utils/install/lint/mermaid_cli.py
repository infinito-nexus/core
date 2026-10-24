"""Install @mermaid-js/mermaid-cli (mmdc) and the chrome-headless-shell it renders with.

mmdc comes from npm with ``PUPPETEER_SKIP_DOWNLOAD`` set; the browser is
provisioned afterwards through the puppeteer that npm installed next to mmdc,
at the revision its puppeteer-core pins. ``unzip`` is ensured first because
puppeteer extracts the browser with it. Puppeteer installs the browser's
shared libraries only through apt-get (``--install-deps``); on dnf, yum and
pacman the libraries ``ldd`` reports missing are installed by soname, and a
font by the distribution's font provide, because the browser aborts in its
font fallback (``SkFontMgr_FontConfigInterface ... Not implemented``) on a
host without any font. Every failure aborts ``install-lint``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from utils.install.npm import npm_install_global
from utils.install.primitives import log, run_privileged, which
from utils.install.system_pkg import detect_package_manager, install_command_via_pkg

BROWSER = "chrome-headless-shell"
PROVISION_TIMEOUT_S = 900

FONT_DIRECTORY = Path("/usr/share/fonts")

_INSTALL_ARGV = {
    "dnf": ["dnf", "-y", "install"],
    "yum": ["yum", "-y", "install"],
    "pacman": ["pacman", "-Syu", "--noconfirm", "--needed"],
}

_FONT_PROVIDES = {
    "dnf": "font(:lang=en)",
    "yum": "font(:lang=en)",
    "pacman": "ttf-font",
}


def _ensure_unzip() -> None:
    if not which("unzip"):
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


def browser_executable() -> Path | None:
    revision = browser_revision()
    if revision is None:
        return None
    return next(
        (
            path
            for path in browser_cache().glob(f"*-{revision}/*/{BROWSER}")
            if path.is_file()
        ),
        None,
    )


def missing_libraries(executable: Path) -> list[str]:
    """Return the shared libraries the dynamic loader cannot resolve.

    Args:
        executable: the browser binary.

    Returns:
        Sorted sonames ``ldd`` reports as ``not found``.
    """
    done = subprocess.run(
        ["ldd", str(executable)], capture_output=True, text=True, check=False
    )
    return sorted(
        {line.split()[0] for line in done.stdout.splitlines() if "=> not found" in line}
    )


def fonts_installed() -> bool:
    return FONT_DIRECTORY.is_dir() and any(
        path.is_file() for path in FONT_DIRECTORY.rglob("*")
    )


def browser_installed() -> bool:
    executable = browser_executable()
    return (
        executable is not None
        and not missing_libraries(executable)
        and fonts_installed()
    )


def _provision_browser(puppeteer: Path) -> subprocess.CompletedProcess[str]:
    argv = [
        str(puppeteer.parent / ".bin" / "puppeteer"),
        "browsers",
        "install",
        BROWSER,
    ]
    if os.geteuid() == 0 and which("apt-get"):
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


def _download_browser() -> None:
    puppeteer = _mmdc_puppeteer()
    if puppeteer is None:
        raise RuntimeError(f"Cannot provision {BROWSER}: no puppeteer next to mmdc.")
    log(f"Provisioning {BROWSER} for mmdc via its own puppeteer.")
    done = _provision_browser(puppeteer)
    if done.returncode != 0:
        revision = browser_revision()
        if revision is not None:
            for partial in browser_cache().glob(f"*-{revision}"):
                shutil.rmtree(partial, ignore_errors=True)
        done = _provision_browser(puppeteer)
    if done.returncode != 0:
        raise RuntimeError(
            f"{BROWSER} provisioning failed:\n{done.stdout}{done.stderr}"
        )


def _library_packages(manager: str, sonames: list[str]) -> list[str]:
    """Map sonames to what the package manager installs them by.

    Args:
        manager: the detected package manager.
        sonames: libraries the browser cannot resolve.

    Returns:
        Install arguments for ``manager``.

    Raises:
        RuntimeError: the manager cannot install by soname.
    """
    if manager in ("dnf", "yum"):
        suffix = "()(64bit)" if sys.maxsize > 2**32 else ""
        return [f"{soname}{suffix}" for soname in sonames]
    if manager == "pacman":
        run_privileged(["pacman", "-Fy"])
        packages: set[str] = set()
        for soname in sonames:
            found = subprocess.run(
                ["pacman", "-Fq", f"usr/lib/{soname}"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()
            if found:
                packages.add(found[0].rsplit("/", 1)[-1])
        return sorted(packages)
    raise RuntimeError(
        f"{BROWSER} lacks {', '.join(sonames)} and {manager} cannot install "
        f"libraries by soname; on apt-get they come from --install-deps, which "
        f"needs root."
    )


def _ensure_browser_libraries(executable: Path) -> None:
    missing = missing_libraries(executable)
    if not missing:
        return
    manager = detect_package_manager()
    packages = _library_packages(manager, missing)
    log(f"Installing {BROWSER} libraries via {manager}: {', '.join(packages)}")
    if packages:
        run_privileged([*_INSTALL_ARGV[manager], *packages])
    missing = missing_libraries(executable)
    if missing:
        raise RuntimeError(
            f"{BROWSER} still lacks {', '.join(missing)} after installing "
            f"{packages} via {manager}."
        )


def _ensure_fonts() -> None:
    if fonts_installed():
        return
    manager = detect_package_manager()
    provide = _FONT_PROVIDES.get(manager)
    if provide is None:
        raise RuntimeError(
            f"{BROWSER} finds no font under {FONT_DIRECTORY} and {manager} has "
            f"no font provide; on apt-get the fonts come from --install-deps, "
            f"which needs root."
        )
    log(f"Installing a font for {BROWSER} via {manager}: {provide}")
    run_privileged([*_INSTALL_ARGV[manager], provide])
    if not fonts_installed():
        raise RuntimeError(
            f"{BROWSER} still finds no font under {FONT_DIRECTORY} after "
            f"installing {provide} via {manager}."
        )


def _ensure_browser() -> None:
    executable = browser_executable()
    if executable is None:
        _download_browser()
        executable = browser_executable()
        if executable is None:
            raise RuntimeError(f"{BROWSER} is still missing after provisioning.")
    _ensure_browser_libraries(executable)
    _ensure_fonts()


def ensure() -> None:
    _ensure_unzip()
    if not which("mmdc"):
        log("Missing command 'mmdc'. Installing @mermaid-js/mermaid-cli via npm.")
        os.environ["PUPPETEER_SKIP_DOWNLOAD"] = "1"
        npm_install_global("@mermaid-js/mermaid-cli")
        if not which("mmdc"):
            raise RuntimeError(
                "Command 'mmdc' is still unavailable after installation."
            )
    _ensure_browser()
