"""Where the nfs-ganesha drop-in sends ganesha's log on every distro."""

from __future__ import annotations

import shlex
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

DROP_IN = (
    PROJECT_ROOT
    / "roles"
    / "svc-storage-nfs-server"
    / "files"
    / "nfs-ganesha-restart.conf"
)


def _service_settings() -> list[tuple[str, str]]:
    """Return the [Service] assignments of the drop-in in file order."""
    settings: list[tuple[str, str]] = []
    section = ""
    for raw in read_text(str(DROP_IN)).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Service" and "=" in line:
            key, value = line.split("=", 1)
            settings.append((key.strip(), value.strip()))
    return settings


def _options() -> list[str]:
    """Return the OPTIONS words the drop-in hands to ganesha.nfsd."""
    for key, value in _service_settings():
        if key != "Environment":
            continue
        for assignment in shlex.split(value):
            name, _, words = assignment.partition("=")
            if name == "OPTIONS":
                return shlex.split(words)
    return []


class TestGaneshaUnitOptions(unittest.TestCase):
    def test_the_drop_in_resets_the_distro_environment_files(self):
        self.assertIn(
            ("EnvironmentFile", ""),
            _service_settings(),
            "the Debian and Ubuntu unit reads OPTIONS from /etc/default/nfs-ganesha "
            "(-L /var/log/ganesha/ganesha.log), and an EnvironmentFile overrides "
            "Environment=; without the reset ganesha logs to an unbounded file that "
            "filled the swarm runner disk in CI run 40625679270 (odoo#1, debian)",
        )

    def test_ganesha_logs_to_syslog(self):
        options = _options()
        self.assertIn("-L", options, "OPTIONS must name ganesha's log target")
        self.assertEqual(
            options[options.index("-L") + 1],
            "SYSLOG",
            "the journal caps ganesha's log (SystemMaxUse on the node), a file "
            "under /var/log/ganesha grows without bound",
        )

    def test_ganesha_keeps_the_event_default_level(self):
        options = _options()
        self.assertIn("-N", options, "OPTIONS must state ganesha's default level")
        self.assertEqual(options[options.index("-N") + 1], "NIV_EVENT")

    def test_ganesha_reads_the_role_config(self):
        options = _options()
        self.assertIn("-f", options, "OPTIONS must name the config ganesha reads")
        self.assertEqual(options[options.index("-f") + 1], "/etc/ganesha/ganesha.conf")


if __name__ == "__main__":
    unittest.main()
