from __future__ import annotations

import posixpath
import unittest

from .test_workspace_egress import VOLUMES, render

SERVICE = "egress"
LOG_DIRECTIVES = ("access_log", "cache_log")
ENTRYPOINT_FORWARDED = frozenset(
    {"/var/log/squid/access.log", "/var/log/squid/cache.log"}
)
STDIO_LINES = ("access_log stdio:/dev/stdout", "cache_log stdio:/dev/stderr")


def log_paths(config):
    """Args:
    config: a rendered ``squid.conf``.

    Returns:
        ``{directive: path}`` of every log Squid opens, its ``stdio:`` module
        prefix stripped.
    """
    paths = {}
    for line in config.splitlines():
        fields = line.split()
        if fields and fields[0] in LOG_DIRECTIVES:
            paths[fields[0]] = fields[1].removeprefix("stdio:")
    return paths


def tmpfs_targets(volumes=VOLUMES, service=SERVICE):
    """Args:
    volumes: the parsed ``meta/volumes.yml``.
    service: the service whose tmpfs mounts are collected.

    Returns:
        Every tmpfs target the service mounts.
    """
    return {
        mount["target"]
        for entry in volumes.values()
        if entry.get("type") == "tmpfs"
        for mount in entry.get("mounts") or []
        if mount.get("service") == service
    }


def log_findings(config, volumes=VOLUMES):
    """Args:
    config: a rendered ``squid.conf``.
    volumes: the parsed ``meta/volumes.yml``.

    Returns:
        Every log directive that is missing, writes outside a tmpfs of the
        egress, or names a file the image entrypoint does not forward.
    """
    paths = log_paths(config)
    writable = tmpfs_targets(volumes)
    findings = [
        f"{directive} is not set"
        for directive in LOG_DIRECTIVES
        if directive not in paths
    ]
    for directive, path in sorted(paths.items()):
        if posixpath.dirname(path) not in writable:
            findings.append(f"{directive} writes {path} outside a tmpfs of the egress")
        if path not in ENTRYPOINT_FORWARDED:
            findings.append(
                f"{directive} writes {path}, which no entrypoint tail forwards"
            )
    return findings


class TestEgressLogs(unittest.TestCase):
    def test_squid_logs_to_files_the_entrypoint_forwards(self):
        config = render("squid.conf", [])
        self.assertEqual(log_findings(config), [])
        self.assertEqual(set(log_paths(config).values()), ENTRYPOINT_FORWARDED)

    def test_negative_control_logs_on_the_stdio_pipes_are_reported(self):
        config = render("squid.conf", [])
        lines = [
            line for line in config.splitlines() if not line.startswith(LOG_DIRECTIVES)
        ]
        stdio = "\n".join([*lines, *STDIO_LINES])
        self.assertEqual(
            log_findings(stdio),
            [
                "access_log writes /dev/stdout outside a tmpfs of the egress",
                "access_log writes /dev/stdout, which no entrypoint tail forwards",
                "cache_log writes /dev/stderr outside a tmpfs of the egress",
                "cache_log writes /dev/stderr, which no entrypoint tail forwards",
            ],
        )

    def test_negative_control_a_log_dir_without_tmpfs_is_reported(self):
        volumes = {
            name: entry
            for name, entry in VOLUMES.items()
            if entry.get("type") != "tmpfs"
        }
        self.assertEqual(
            log_findings(render("squid.conf", []), volumes),
            [
                "access_log writes /var/log/squid/access.log outside a tmpfs of the egress",
                "cache_log writes /var/log/squid/cache.log outside a tmpfs of the egress",
            ],
        )


if __name__ == "__main__":
    unittest.main()
