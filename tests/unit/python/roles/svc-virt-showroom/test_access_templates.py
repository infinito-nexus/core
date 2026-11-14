from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT

SUDOERS = "roles/svc-virt-showroom/templates/sudoers.j2"
BASTION = "roles/svc-virt-showroom/templates/sshd_bastion.conf.j2"
SSHD_CONFIG = "roles/sys-svc-sshd/templates/sshd_config.j2"

INSTANCES = [
    {"project": "karakalpak", "name": "karakalpak"},
    {"project": "lab", "name": "lab"},
]
PROJECTS = {
    "karakalpak": {"address": "192.168.245.10"},
    "lab": {"address": "192.168.245.11"},
}


def _env() -> Environment:
    env = Environment(
        trim_blocks=True,
        undefined=StrictUndefined,
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    env.filters["ternary"] = lambda value, yes, no: yes if value else no
    return env


def _lines(template: str, **context) -> list[str]:
    rendered = _env().get_template(template).render(**context)
    return [" ".join(line.split()) for line in rendered.splitlines() if line.strip()]


def _sudoers(instances: list[dict[str, str]]) -> list[str]:
    return _lines(
        SUDOERS,
        SHOWROOM_INSTANCES=instances,
        SHOWROOM_OPERATOR_USER="incus-operator",
        SHOWROOM_INCUS_BIN="/usr/bin/incus",
    )


def _bastion(projects: dict[str, dict[str, str]]) -> list[str]:
    return _lines(
        BASTION, SHOWROOM_PROJECTS=projects, SHOWROOM_BASTION_USER="incus-bastion"
    )


class TestOperatorSudoers(unittest.TestCase):
    def test_grants_exactly_one_root_shell_per_server(self) -> None:
        self.assertEqual(
            [
                "incus-operator ALL=(root) /usr/bin/incus exec --project karakalpak karakalpak -- /bin/bash -l",
                "incus-operator ALL=(root) /usr/bin/incus exec --project lab lab -- /bin/bash -l",
            ],
            _sudoers(INSTANCES),
        )

    def test_asks_for_the_password_and_allows_no_wildcard(self) -> None:
        for line in _sudoers(INSTANCES):
            self.assertNotIn("NOPASSWD", line)
            self.assertNotIn("*", line)

    def test_no_server_grants_nothing(self) -> None:
        self.assertEqual([], _sudoers([]))


class TestBastionDropIn(unittest.TestCase):
    def test_matches_only_the_bastion_user(self) -> None:
        self.assertEqual("Match User incus-bastion", _bastion(PROJECTS)[0])

    def test_forwards_only_to_port_22_of_every_server(self) -> None:
        lines = _bastion(PROJECTS)
        self.assertIn("PermitOpen 192.168.245.10:22 192.168.245.11:22", lines)
        self.assertIn("AllowTcpForwarding local", lines)

    def test_no_server_opens_nothing(self) -> None:
        self.assertIn("PermitOpen none", _bastion({}))

    def test_gives_no_shell_listener_tty_or_agent(self) -> None:
        lines = _bastion(PROJECTS)
        for directive in (
            "PermitListen none",
            "PermitTTY no",
            "AllowAgentForwarding no",
            "AllowStreamLocalForwarding no",
            "X11Forwarding no",
            "PermitTunnel no",
            "ForceCommand /usr/sbin/nologin",
        ):
            self.assertIn(directive, lines)


class TestSshdConfigIncludesRoleDropIns(unittest.TestCase):
    def test_reads_the_role_drop_ins_after_every_global_setting(self) -> None:
        lines = _lines(
            SSHD_CONFIG,
            lookup=lambda name, *terms: False,
            SYS_SVC_SSHD_PERMIT_ROOT_LOGIN="no",
            SYS_SVC_SSHD_PASSWORD_AUTHENTICATION=False,
            DIR_SSHD_DROPINS="/etc/infinito.nexus/sshd",
            ansible_facts={"os_family": "Debian"},
        )
        self.assertEqual("Include /etc/infinito.nexus/sshd/*.conf", lines[-1])
        self.assertIn("PermitRootLogin no", lines)


if __name__ == "__main__":
    unittest.main()
