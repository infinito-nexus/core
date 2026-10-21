"""Node.js runtime provisioning for the lint toolchain and the JavaScript unit suite."""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from utils.install.primitives import download_file, log, run_privileged
from utils.install.system_pkg import ensure_command_present

DIST_URL = "https://nodejs.org/dist"
SCHEDULE_URL = "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json"
KEYRING_URL = "https://raw.githubusercontent.com/nodejs/release-keys/main/gpg-only-active-keys/pubring.kbx"
PREFIX = Path("/usr/local")
ARCHITECTURES = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def installed_line() -> str:
    """Return the release line of the ``node`` on PATH, such as ``v20``.

    Returns:
        The major version prefixed with ``v``, as the release schedule keys it.
    """
    version = subprocess.run(
        ["node", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return version.split(".", 1)[0]


def line_is_supported(line: str, schedule: dict, today: dt.date) -> bool:
    """Tell whether a release line still receives upstream fixes.

    Args:
        line: release line such as ``v20``.
        schedule: the parsed nodejs/Release ``schedule.json``.
        today: the date the end of life is compared against.

    Returns:
        False for an unknown line and for a line past its ``end`` date.
    """
    entry = schedule.get(line)
    if entry is None:
        return False
    return dt.date.fromisoformat(entry["end"]) >= today


def newest_lts(index: list) -> str:
    """Return the version of the newest LTS release in ``index.json``.

    Args:
        index: the parsed ``https://nodejs.org/dist/index.json``, newest first.

    Raises:
        RuntimeError: the index lists no LTS release.
    """
    for release in index:
        if release["lts"]:
            return release["version"]
    raise RuntimeError(f"{DIST_URL}/index.json lists no LTS release")


def tarball_name(version: str, system: str, machine: str) -> str:
    """Return the Linux tarball name of a release for this host.

    Args:
        version: release version such as ``v24.22.1``.
        system: ``platform.system()`` of the host.
        machine: ``platform.machine()`` of the host.

    Raises:
        RuntimeError: the host is not Linux, or Node.js publishes no Linux
            build for the machine.
    """
    if system != "Linux":
        raise RuntimeError(
            f"The upstream Node.js install supports Linux only; install a "
            f"supported Node.js through the package manager on {system}."
        )
    arch = ARCHITECTURES.get(machine)
    if arch is None:
        raise RuntimeError(f"No Node.js Linux build for machine {machine!r}")
    return f"node-{version}-linux-{arch}.tar.gz"


def expected_sha256(shasums: Path, name: str) -> str:
    """Return the checksum ``SHASUMS256.txt`` records for a file.

    Args:
        shasums: the downloaded ``SHASUMS256.txt``.
        name: file name to look up.

    Raises:
        RuntimeError: the file is not listed.
    """
    with shasums.open(encoding="utf-8") as handle:
        for line in handle:
            digest, _, listed = line.strip().partition("  ")
            if listed == name:
                return digest
    raise RuntimeError(f"{name} is not listed in {shasums.name}")


def _verify_signature(workdir: Path, shasums: Path, signature: Path) -> None:
    ensure_command_present("gpgv")
    keyring = workdir / "pubring.kbx"
    download_file(KEYRING_URL, str(keyring))
    subprocess.run(
        ["gpgv", "--keyring", str(keyring), str(signature), str(shasums)],
        check=True,
    )


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def install_upstream_lts() -> str:
    """Install the newest Node.js LTS from nodejs.org under ``PREFIX``.

    Returns:
        The installed version.

    Raises:
        RuntimeError: the checksum does not match, or ``node`` on PATH is not
            the installed release afterwards.
        subprocess.CalledProcessError: the signature does not verify.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        index = workdir / "index.json"
        download_file(f"{DIST_URL}/index.json", str(index))
        version = newest_lts(_load_json(index))
        name = tarball_name(version, platform.system(), platform.machine())
        shasums = workdir / "SHASUMS256.txt"
        signature = workdir / "SHASUMS256.txt.sig"
        download_file(f"{DIST_URL}/{version}/SHASUMS256.txt", str(shasums))
        download_file(f"{DIST_URL}/{version}/SHASUMS256.txt.sig", str(signature))
        _verify_signature(workdir, shasums, signature)
        tarball = workdir / name
        log(f"Installing Node.js {version} from {DIST_URL} into {PREFIX}")
        download_file(f"{DIST_URL}/{version}/{name}", str(tarball), timeout=300.0)
        if _sha256(tarball) != expected_sha256(shasums, name):
            raise RuntimeError(f"{name} does not match its SHASUMS256.txt entry")
        top = name.removesuffix(".tar.gz")
        run_privileged(
            [
                "tar",
                "-xzf",
                str(tarball),
                "-C",
                str(PREFIX),
                "--strip-components=1",
                f"{top}/bin",
                f"{top}/include",
                f"{top}/lib",
                f"{top}/share",
            ]
        )
    resolved = shutil.which("node")
    line = installed_line()
    if resolved != str(PREFIX / "bin" / "node") or line != version.split(".", 1)[0]:
        raise RuntimeError(
            f"node on PATH is {resolved!r} ({line}) after installing {version} "
            f"into {PREFIX}"
        )
    return version


@functools.cache
def ensure_node_present() -> None:
    """Provide a ``node`` whose release line is still supported upstream.

    Raises:
        RuntimeError: node is still absent after the install attempt, or the
            upstream install failed its checks.
    """
    ensure_command_present("node")
    line = installed_line()
    with tempfile.TemporaryDirectory() as tmp:
        schedule = Path(tmp) / "schedule.json"
        download_file(SCHEDULE_URL, str(schedule))
        supported = line_is_supported(
            line, _load_json(schedule), dt.datetime.now(dt.UTC).date()
        )
    if supported:
        return
    log(f"Node.js {line} on PATH has reached its end of life upstream.")
    install_upstream_lts()


if __name__ == "__main__":
    ensure_node_present()
