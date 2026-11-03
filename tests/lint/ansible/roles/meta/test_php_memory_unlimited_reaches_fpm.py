"""Lint guard: the interim ``memory_limit = -1`` ini MUST reach PHP-FPM.

A role carries the CVE-2026-109618 mitigation by mounting
``FILE_PHP_MEMORY_UNLIMITED_INI`` (``php_memory_unlimited`` in ``meta/volumes.yml``)
into the conf.d of its image. FPM keeps ``-1`` only while nothing later sets
``memory_limit`` again: a later ini in the same scan dir, a pool ``php_value`` or
``php_admin_value``, a FastCGI ``PHP_VALUE`` or ``PHP_ADMIN_VALUE``, or a
``PHP_MEMORY_LIMIT`` env that the image writes into its pool as
``php_admin_value`` (``nfrastack/fusiondirectory`` does).

Each mount MUST share the directory of the same service's ``php_hardening`` mount,
the scan dir ``sys-ctl-hlth-runtime`` verifies on the live container, and MUST sort
after every other ini the role mounts there. No file under the role's
``templates/`` or ``files/`` may set a ``memory_limit`` other than ``-1`` through
the pool or FastCGI, and ``templates/env.j2`` and ``templates/compose.yml.j2`` may
not pass a ``PHP_MEMORY_LIMIT`` other than ``-1``. Overrides the image itself ships,
or upstream files the role copies at runtime (Magento's ``nginx.conf.sample``), are
outside the repository and stay a runtime check.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping

MITIGATION = "php_memory_unlimited"
HARDENING = "php_hardening"
ENV_TEMPLATES = ("templates/env.j2", ROLE_FILE_TEMPL_COMPOSE)
SCANNED_DIRS = ("templates", "files")

_UNLIMITED = "-1"
_COMMENT = ("#", ";", "//", "{#")
_POOL = re.compile(
    r"\bphp_(?:admin_)?value\s*\[\s*memory_limit\s*\]\s*=\s*(?P<value>[^\s;]+)",
    re.IGNORECASE,
)
_FASTCGI = re.compile(
    r"\bPHP_(?:ADMIN_)?VALUE\b.*?\bmemory_limit\s*=\s*(?P<value>[^\s\"';\\]+)"
)
_ENV = re.compile(r"^\s*(?:-\s*)?[\"']?PHP_MEMORY_LIMIT[\"']?\s*[=:]\s*(?P<value>\S+)")


def _limit(value: str) -> str:
    return value.strip().strip("\"'")


def mount_findings(volumes: Mapping[str, Any]) -> list[str]:
    """Return why the mitigation mounts of one role cannot reach PHP-FPM.

    Args:
        volumes: the parsed ``meta/volumes.yml`` of the role.
    """
    scan_dirs = {
        mount["service"]: PurePosixPath(mount["target"]).parent
        for mount in volumes.get(HARDENING, {}).get("mounts") or []
    }
    inis: dict[tuple[str, PurePosixPath], list[str]] = defaultdict(list)
    for entry in volumes.values():
        if not isinstance(entry, dict):
            continue
        for mount in entry.get("mounts") or []:
            target = PurePosixPath(str(mount.get("target", "")))
            if target.suffix == ".ini":
                inis[(mount.get("service"), target.parent)].append(target.name)

    findings = []
    for mount in volumes[MITIGATION].get("mounts") or []:
        service = mount["service"]
        target = PurePosixPath(mount["target"])
        if service not in scan_dirs:
            findings.append(
                f"{service}: no {HARDENING} mount, so nothing verifies "
                f"{target.parent} as the scan dir"
            )
            continue
        if target.parent != scan_dirs[service]:
            findings.append(
                f"{service}: {target} is outside the scan dir {scan_dirs[service]}"
            )
        later = sorted(n for n in inis[(service, target.parent)] if n > target.name)
        if later:
            findings.append(
                f"{service}: {', '.join(later)} sorts after {target.name} and wins"
            )
    return findings


def text_findings(relative: str, text: str) -> list[str]:
    """Return the lines of one role file that set ``memory_limit`` after the ini.

    Args:
        relative: the file's path inside its role, e.g. ``templates/env.j2``.
        text: the file's content.
    """
    patterns = [_POOL, _FASTCGI]
    if relative in ENV_TEMPLATES:
        patterns.append(_ENV)
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(_COMMENT):
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if match and _limit(match["value"]) != _UNLIMITED:
                findings.append(f"{relative}:{number}: {line.strip()}")
    return findings


def carriers() -> dict[str, dict[str, Any]]:
    """Return ``{role: volumes}`` for every role that mounts the mitigation."""
    found = {}
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}")):
        volumes = load_yaml_any(str(path), default_if_missing={})
        if isinstance(volumes, dict) and MITIGATION in volumes:
            found[path.parent.parent.name] = volumes
    return found


def role_files(role: str) -> list[tuple[str, str]]:
    """Return ``(path inside the role, text)`` for the role's scanned files.

    Args:
        role: the role directory name.
    """
    root = PROJECT_ROOT / "roles" / role
    files = []
    for path in iter_project_files(exclude_tests=True):
        relative = Path(path).relative_to(PROJECT_ROOT)
        if relative.parts[:2] != ("roles", role) or len(relative.parts) < 4:
            continue
        if relative.parts[2] not in SCANNED_DIRS:
            continue
        try:
            text = read_text(path)
        except UnicodeDecodeError:
            continue
        files.append((Path(path).relative_to(root).as_posix(), text))
    return files


class TestPhpMemoryUnlimitedReachesFpm(unittest.TestCase):
    def test_every_carrier_lets_the_ini_reach_fpm(self) -> None:
        roles = carriers()
        self.assertTrue(
            roles,
            f"no role mounts {MITIGATION} any more: delete this lint together "
            "with memory-unlimited.ini, its install task and "
            "FILE_PHP_MEMORY_UNLIMITED_INI",
        )
        offenders = []
        for role, volumes in roles.items():
            findings = mount_findings(volumes)
            for relative, text in role_files(role):
                findings += text_findings(relative, text)
            offenders += [f"- roles/{role}: {finding}" for finding in findings]
        self.assertEqual(
            offenders,
            [],
            "These roles mount the memory_limit = -1 ini but also set "
            "memory_limit where PHP-FPM reads it after that ini:\n"
            + "\n".join(offenders),
        )


class TestMountFindings(unittest.TestCase):
    HARDENED: ClassVar[dict[str, Any]] = {
        HARDENING: {
            "mounts": [
                {
                    "service": "php",
                    "target": "/etc/php/conf.d/zz-infinito-hardening.ini",
                }
            ]
        },
        MITIGATION: {
            "mounts": [
                {
                    "service": "php",
                    "target": "/etc/php/conf.d/zz-infinito-memory-unlimited.ini",
                }
            ]
        },
    }

    def test_a_mount_beside_the_hardening_ini_passes(self) -> None:
        self.assertEqual(mount_findings(self.HARDENED), [])

    def test_a_mount_outside_the_scan_dir_is_flagged(self) -> None:
        volumes = {
            **self.HARDENED,
            MITIGATION: {
                "mounts": [{"service": "php", "target": "/etc/php/zz-memory.ini"}]
            },
        }
        self.assertEqual(
            mount_findings(volumes),
            ["php: /etc/php/zz-memory.ini is outside the scan dir /etc/php/conf.d"],
        )

    def test_a_service_without_hardening_is_flagged(self) -> None:
        volumes = {MITIGATION: self.HARDENED[MITIGATION]}
        self.assertEqual(len(mount_findings(volumes)), 1)

    def test_a_later_ini_in_the_scan_dir_is_flagged(self) -> None:
        volumes = {
            **self.HARDENED,
            "app_ini": {
                "mounts": [
                    {"service": "php", "target": "/etc/php/conf.d/zz-uploads.ini"}
                ]
            },
        }
        self.assertEqual(
            mount_findings(volumes),
            [
                "php: zz-uploads.ini sorts after zz-infinito-memory-unlimited.ini and wins"
            ],
        )

    def test_a_later_ini_of_another_service_is_ignored(self) -> None:
        volumes = {
            **self.HARDENED,
            "app_ini": {
                "mounts": [
                    {"service": "cron", "target": "/etc/php/conf.d/zz-uploads.ini"}
                ]
            },
        }
        self.assertEqual(mount_findings(volumes), [])


class TestTextFindings(unittest.TestCase):
    def test_a_pool_admin_value_is_flagged(self) -> None:
        text = "[www]\nphp_admin_value[memory_limit] = 128M\n"
        self.assertEqual(
            text_findings("templates/php-fpm.conf.j2", text),
            ["templates/php-fpm.conf.j2:2: php_admin_value[memory_limit] = 128M"],
        )

    def test_a_fastcgi_php_value_is_flagged(self) -> None:
        line = 'fastcgi_param PHP_VALUE "memory_limit=756M \\n max_execution_time=600";'
        self.assertEqual(len(text_findings("templates/nginx.conf.j2", line)), 1)

    def test_the_former_magento_env_line_is_flagged(self) -> None:
        line = (
            "PHP_MEMORY_LIMIT={{ lookup('service_memory_mb', application_id, "
            "'php', 0.75) }}M"
        )
        self.assertEqual(len(text_findings("templates/env.j2", line)), 1)

    def test_a_compose_environment_entry_is_flagged(self) -> None:
        line = "      PHP_MEMORY_LIMIT: 512M"
        self.assertEqual(len(text_findings(ROLE_FILE_TEMPL_COMPOSE, line)), 1)

    def test_unlimited_values_pass(self) -> None:
        text = (
            "PHP_MEMORY_LIMIT=-1\n"
            "php_admin_value[memory_limit] = -1\n"
            'fastcgi_param PHP_ADMIN_VALUE "memory_limit=-1";'
        )
        self.assertEqual(text_findings("templates/env.j2", text), [])

    def test_a_shell_variable_in_a_script_is_not_env(self) -> None:
        line = 'PHP_MEMORY_LIMIT="${INIT_PHP_MEMORY_LIMIT:?}"'
        self.assertEqual(text_findings("files/shell/init.sh", line), [])

    def test_a_commented_override_is_ignored(self) -> None:
        line = "; php_admin_value[memory_limit] = 1G"
        self.assertEqual(text_findings("templates/php-fpm.conf.j2", line), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
