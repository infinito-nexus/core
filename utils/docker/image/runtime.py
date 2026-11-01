from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.docker.image.pin import is_digest
from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name
from utils.docker.registry import config_blob
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

FLOORS_FILE = PROJECT_ROOT / "roles" / "sys-ctl-hlth-runtime" / ROLE_FILE_VARS_MAIN
FLOORS_KEY = "HEALTH_RUNTIME_FLOORS"
USER_AGENT = "infinito-nexus-runtime-report"
PHP_VERSION_PATTERN = re.compile(r"\bPHP_VERSION=([0-9][^\s\"';]*)")
PHP_BASE_PATTERN = re.compile(r"\bPHP_BASE=(\d+\.\d+)(?![\d.])")
PACKAGE_INSTALL_PATTERN = re.compile(
    r"\b(?:apk\s+(?:-\S+\s+)*add|(?:apt-get|apt|dnf|microdnf|yum)\s+(?:-\S+\s+)*install)\b"
)
PHP_PACKAGE_PATTERN = re.compile(
    r"(?<!\S)(?:[\w.+]+-)*php(\d)(?:\.?(\d))?(?:-[\w.+-]+)?(?:=\S*?)?(?=[;&|\\]*(?:\s|$))"
)
PHP_UNVERSIONED_PACKAGE_PATTERN = re.compile(
    r"(?<!\S)(php|php-(?:cli|fpm|cgi|phpdbg)|libapache2-mod-php)(?:=\S*?)?(?=[;&|\\]*(?:\s|$))"
)
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class PhpRuntime:
    """PHP found in an image's build record.

    Args:
        version: ``PHP_VERSION`` the image sets, ``None`` when it sets none.
        lines: ``major[.minor]`` lines named by distro PHP packages or a
            ``PHP_BASE`` build argument.
        packages: unversioned distro packages that are the interpreter itself
            (``php``, ``php-cli``, ``php-fpm``, ``php-cgi``, ``php-phpdbg``,
            ``libapache2-mod-php``); they name no line. Extension and library
            packages such as ``php-mysql`` or ``php-pear`` do not count.
    """

    version: str | None
    lines: tuple[str, ...]
    packages: tuple[str, ...]


def load_php_floors() -> dict[str, str]:
    """Return ``{"<major>.<minor>": "<lowest patched version>"}`` from the SPOT."""
    return load_yaml_any(str(FLOORS_FILE))[FLOORS_KEY]["php"]


def _hub_instructions(
    repository: str, tag: str, os_name: str, architecture: str
) -> list[str] | None:
    url = (
        f"https://hub.docker.com/v2/repositories/{quote(repository, safe='/')}"
        f"/tags/{quote(tag, safe='')}/images"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - https request to hub.docker.com
            images = json.loads(response.read().decode())
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None
    if not isinstance(images, list):
        return None
    for image in images:
        if (
            isinstance(image, dict)
            and image.get("os") == os_name
            and image.get("architecture") == architecture
        ):
            return [
                str(layer.get("instruction") or "")
                for layer in image.get("layers") or []
                if isinstance(layer, dict)
            ]
    return None


def _oci_instructions(
    image: str, reference: str, os_name: str, architecture: str
) -> list[str] | None:
    blob = config_blob(image, reference, os_name, architecture)
    if blob is None:
        return None
    history = [
        str(step.get("created_by") or "")
        for step in blob.get("history") or []
        if isinstance(step, dict)
    ]
    env = [f"ENV {item}" for item in (blob.get("config") or {}).get("Env") or []]
    return history + env


def build_instructions(
    image: str,
    reference: str,
    *,
    os_name: str,
    architecture: str,
) -> list[str] | None:
    """Return the build instructions of ``image:reference`` without pulling it.

    Args:
        image: image name, with or without registry host.
        reference: tag or digest.
        os_name: platform to resolve a multi-arch index to.
        architecture: platform to resolve a multi-arch index to.

    Returns:
        The image's history plus its final ``ENV`` lines, or ``None`` when the
        registry gave no answer. A Docker Hub tag is read through the Hub API,
        which a pull rate limit does not meter; every other image through its
        OCI config blob.
    """
    parsed = split_registry_and_name(image)
    if parsed is None:
        return None
    registry, name = parsed
    on_hub = registry is None or registry in DOCKER_HUB_REGISTRIES
    if on_hub and not is_digest(reference):
        repository = name if "/" in name else f"library/{name}"
        return _hub_instructions(repository, reference, os_name, architecture)
    return _oci_instructions(image, reference, os_name, architecture)


def php_runtime(instructions: list[str]) -> PhpRuntime | None:
    """Read the PHP an image ships from its build instructions.

    Args:
        instructions: see :func:`build_instructions`.

    Returns:
        The last ``PHP_VERSION`` set, the lines of the distro PHP packages
        and ``PHP_BASE`` arguments, and the unversioned interpreter packages,
        or ``None`` when none of them appears.
    """
    version = None
    lines: set[str] = set()
    packages: set[str] = set()
    for instruction in instructions:
        for match in PHP_VERSION_PATTERN.finditer(instruction):
            version = match.group(1)
        lines.update(PHP_BASE_PATTERN.findall(instruction))
        if not PACKAGE_INSTALL_PATTERN.search(instruction):
            continue
        for major, minor in PHP_PACKAGE_PATTERN.findall(instruction):
            lines.add(f"{major}.{minor}" if minor else major)
        packages.update(PHP_UNVERSIONED_PACKAGE_PATTERN.findall(instruction))
    if version is None and not lines and not packages:
        return None
    return PhpRuntime(
        version=version,
        lines=tuple(sorted(lines)),
        packages=tuple(sorted(packages)),
    )


def _numbers(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def php_finding(runtime: PhpRuntime, floors: dict[str, str]) -> str | None:
    """Judge an image's PHP against the floors.

    Args:
        runtime: see :func:`php_runtime`.
        floors: see :func:`load_php_floors`.

    Returns:
        ``None`` when nothing is below its floor, otherwise the reason. The
        lines are judged next to ``PHP_VERSION``, so an end-of-life package
        line fails an image whose ``PHP_VERSION`` is patched. Unversioned
        packages alone are no finding: their patch level is unknown.
    """
    oldest = min(_numbers(line) for line in floors)
    newest = max(_numbers(line) for line in floors)
    if runtime.version is not None:
        match = VERSION_PATTERN.match(runtime.version)
        if match is None:
            return f"unparsable PHP_VERSION {runtime.version!r}"
        current = tuple(int(part) for part in match.groups())
        line = f"{current[0]}.{current[1]}"
        if line in floors and current < _numbers(floors[line]):
            return f"{runtime.version} is below the security floor {floors[line]}"
        if line not in floors and current[:2] <= newest:
            return f"{runtime.version} runs the end-of-life line {line}"
    eol = [line for line in runtime.lines if _numbers(line) < oldest]
    if eol:
        return f"line {', '.join(eol)} is end of life"
    return None
