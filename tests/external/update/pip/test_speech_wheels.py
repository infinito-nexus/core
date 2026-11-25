from __future__ import annotations

import http.client
import json
import re
import unittest
import urllib.error
import urllib.request

from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from utils.annotations.message import warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.github.variant.pools import ARCHITECTURES
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles" / "svc-ai-speech"
REQUIREMENTS = ROLE_DIR / "files" / "python" / "requirements.txt"
BUILD_SERVICE = "piper"
PYPI_RELEASE = "https://pypi.org/pypi/{}/{}/json"
TIMEOUT_SECONDS = 15
USER_AGENT = "infinito-nexus speech wheel check"
MACHINE_BY_ARCHITECTURE = {"amd64": "x86_64", "arm64": "aarch64"}
PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>\S+)")
HASH = re.compile(r"--hash=sha256:(?P<digest>[0-9a-f]{64})")
MINOR = re.compile(r"^3\.(?P<minor>\d+)")
LINUX_PLATFORMS = ("manylinux", "linux_")


class PyPIUnavailableError(Exception):
    """PyPI did not answer with usable JSON."""


def pinned(requirements: str) -> list[tuple[str, str, set[str]]]:
    """
    Args:
        requirements: a pip requirements file in ``--require-hashes`` form.

    Returns:
        ``(name, version, sha256 digests)`` per requirement.
    """
    found = []
    for line in requirements.replace("\\\n", " ").splitlines():
        match = PIN.match(line.strip())
        if match:
            digests = {hashed["digest"] for hashed in HASH.finditer(line)}
            found.append((match["name"], match["version"], digests))
    return found


def installable(filename: str, minor: int, machine: str) -> bool:
    """
    Args:
        filename: a distribution file name from PyPI.
        minor: the Python 3 minor of the build's base image.
        machine: the kernel machine name, ``x86_64`` or ``aarch64``.

    Returns:
        Whether pip on a glibc Linux of *machine* with CPython 3.*minor*
        installs the file under ``--only-binary=:all:``.
    """
    try:
        _name, _version, _build, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    for tag in tags:
        platform_ok = tag.platform == "any" or (
            tag.platform.startswith(LINUX_PLATFORMS)
            and tag.platform.endswith(f"_{machine}")
        )
        exact = tag.interpreter in {f"cp3{minor}", "py3", f"py3{minor}"}
        stable = (
            tag.abi == "abi3"
            and tag.interpreter.startswith("cp3")
            and tag.interpreter[3:].isdigit()
            and int(tag.interpreter[3:]) <= minor
        )
        if platform_ok and (exact or stable):
            return True
    return False


def missing(files: dict[str, list[str]], minor: int, machine: str) -> list[str]:
    """
    Args:
        files: requirement label to the file names its pinned digests name.
        minor: the Python 3 minor of the build's base image.
        machine: the kernel machine name.

    Returns:
        The labels with no pinned file pip installs on *machine*.
    """
    return sorted(
        label
        for label, names in files.items()
        if not any(installable(name, minor, machine) for name in names)
    )


def release_files(name: str, version: str) -> list[dict]:
    """
    Args:
        name: the distribution name.
        version: the pinned version.

    Returns:
        The ``urls`` entries of the release on PyPI.

    Raises:
        PyPIUnavailableError: the request failed or returned no JSON.
    """
    url = PYPI_RELEASE.format(name, version)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - fixed https PyPI origin, path from the role's pinned requirement names
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https PyPI origin, path from the role's pinned requirement names
            return json.loads(response.read().decode()).get("urls") or []
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ) as exc:
        raise PyPIUnavailableError(f"{name}=={version}: {exc}") from exc


def _base_minor() -> int:
    version = str(
        load_yaml(str(ROLE_DIR / ROLE_FILE_META_SERVICES))[BUILD_SERVICE]["version"]
    )
    return int(MINOR.match(version)["minor"])


class TestSpeechWheels(unittest.TestCase):
    def test_every_matrix_architecture_finds_a_pinned_wheel(self) -> None:
        files: dict[str, list[str]] = {}
        for name, version, digests in pinned(read_text(str(REQUIREMENTS))):
            try:
                released = release_files(name, version)
            except PyPIUnavailableError as exc:
                warning(str(exc), title="🔍 PyPI did not answer")
                self.skipTest(str(exc))
            files[f"{name}=={version}"] = [
                entry["filename"]
                for entry in released
                if entry.get("digests", {}).get("sha256") in digests
            ]
        minor = _base_minor()
        offenders = [
            f"{architecture}: {label} pins no wheel pip installs on "
            f"{MACHINE_BY_ARCHITECTURE[architecture]} with CPython 3.{minor}"
            for architecture in ARCHITECTURES
            for label in missing(files, minor, MACHINE_BY_ARCHITECTURE[architecture])
        ]
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_a_pin_set_without_an_aarch64_wheel_is_caught(self) -> None:
        files = {
            "onnxruntime==1.31.1": [
                "onnxruntime-1.31.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
            ],
            "piper-tts==1.8.0": [
                "piper_tts-1.8.0-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                "piper_tts-1.8.0-cp39-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
            ],
            "packaging==26.3": ["packaging-26.3-py3-none-any.whl"],
        }

        self.assertEqual([], missing(files, 12, "x86_64"))
        self.assertEqual(["onnxruntime==1.31.1"], missing(files, 12, "aarch64"))

    def test_a_wheel_for_another_cpython_is_not_installable(self) -> None:
        self.assertFalse(
            installable(
                "numpy-2.5.4-cp313-cp313-manylinux_2_28_aarch64.whl", 12, "aarch64"
            )
        )
        self.assertFalse(installable("numpy-2.5.4.tar.gz", 12, "aarch64"))


if __name__ == "__main__":
    unittest.main()
