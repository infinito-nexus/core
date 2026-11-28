from __future__ import annotations

import io
import json
import re
import subprocess
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from types import SimpleNamespace

from utils import PROJECT_ROOT
from utils.platform_monitoring import AGENT_SECTION, WORKSPACE_ID, agent_key_line

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-checkmk"
    / "files"
    / "python"
    / "infinito_agent_ssh.py"
)
NAME = "ws-0a1b2c3d-0000-4000-8000-00000000000a-target"
BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
LABELS = {
    "workspace": "ws-0a1b2c3d-0000-4000-8000-00000000000a",
    "infinito/ssh_user": "deploy",
    "infinito/ssh_port": "22",
    "infinito/ssh_host_key_type": "ssh-ed25519",
    "infinito/ssh_host_key": BLOB,
}
ENV = {"OMD_ROOT": "/omd/sites/cmk"}


def _load():
    spec = spec_from_file_location("infinito_agent_ssh", SCRIPT)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = _load()


WORKSPACE = LABELS["workspace"]
OTHER = "ws-0a1b2c3d-0000-4000-8000-00000000000b"
AGENT = b"<<<check_mk>>>\nVersion: 2.4.0p42\n<<<df>>>\n/dev/sda1 100 50\n"


def bound_line(workspace):
    return agent_key_line(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterial0123456789abcdefgh",
        "192.0.2.7",
        workspace.removeprefix("ws-"),
    )


def forced_output(line):
    """Args:
    line: the ``authorized_keys`` line a host's own deploy wrote.

    Returns:
        What sshd's forced command of ``line`` prints, its ``check_mk_agent``
        standing in as ``AGENT``.
    """
    forced = re.match(r'command="([^"]*)"', line).group(1)
    return subprocess.run(
        ["/bin/sh", "-c", forced.replace("exec check_mk_agent", "cat")],
        input=AGENT,
        capture_output=True,
        check=True,
    ).stdout


def run(labels, name=NAME, address="192.0.2.10", stdout=None, returncode=0):
    queries, commands, out = [], [], io.BytesIO()
    if stdout is None:
        stdout = forced_output(bound_line(WORKSPACE))

    def query(argv, **kwargs):
        queries.append((argv, kwargs["input"]))
        return SimpleNamespace(stdout=json.dumps([[labels]]))

    def ssh(argv, **_kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    code = agent.main([name, address], ENV, query=query, run=ssh, out=out)
    return code, queries, commands, out.getvalue()


class TestTheAgentPull(unittest.TestCase):
    def test_the_host_key_is_pinned_and_no_known_hosts_file_is_used(self) -> None:
        code, queries, (argv,), _ = run(LABELS)
        self.assertEqual(code, 0)
        self.assertEqual(queries[0][0], ["lq"])
        self.assertIn(f"Filter: name = {NAME}\n", queries[0][1])
        options = [argv[i + 1] for i, item in enumerate(argv) if item == "-o"]
        self.assertIn("StrictHostKeyChecking=yes", options)
        self.assertIn("UserKnownHostsFile=/dev/null", options)
        self.assertIn("GlobalKnownHostsFile=/dev/null", options)
        self.assertIn(f"KnownHostsCommand=/bin/echo %H ssh-ed25519 {BLOB}", options)
        self.assertEqual(
            argv[argv.index("-i") + 1], "/omd/sites/cmk/.ssh/infinito_monitoring"
        )
        self.assertEqual(argv[argv.index("-l") + 1], "deploy")
        self.assertEqual(argv[-1], "192.0.2.10")

    def test_a_tampered_label_runs_no_ssh(self) -> None:
        for label, value in (
            ("infinito/ssh_user", "-oProxyCommand=id"),
            ("infinito/ssh_port", "99999"),
            ("infinito/ssh_port", "22 -o x"),
            ("infinito/ssh_host_key_type", "ssh-dss"),
            ("infinito/ssh_host_key", f"{BLOB} extra"),
            ("infinito/ssh_host_key", f"{BLOB}\nssh-rsa AAAA"),
        ):
            with self.subTest(label=label, value=value):
                code, _, commands, _ = run({**LABELS, label: value})
                self.assertEqual((code, commands), (2, []))
        code, _, commands, _ = run(
            {key: value for key, value in LABELS.items() if key != "infinito/ssh_user"}
        )
        self.assertEqual((code, commands), (2, []))

    def test_a_foreign_name_or_address_runs_no_query_and_no_ssh(self) -> None:
        for name, address in (
            ("localhost", "192.0.2.10"),
            (NAME, "-oProxyCommand=id"),
            (f"{NAME}\nGET", "192.0.2.10"),
        ):
            with self.subTest(name=name, address=address):
                code, _, commands, _ = run(LABELS, name, address)
                self.assertEqual((code, commands), (2, []))


class TestTheWorkspaceBinding(unittest.TestCase):
    def test_the_own_workspace_passes_the_agent_output_without_its_section(
        self,
    ) -> None:
        code, _, _, out = run(LABELS)
        self.assertEqual((code, out), (0, AGENT))

    def test_negative_control_another_workspaces_host_prints_nothing(self) -> None:
        for stdout in (
            forced_output(bound_line(OTHER)),
            AGENT,
            b"",
            b"<<<infinito_workspace>>>\n",
        ):
            with self.subTest(stdout=stdout[:40]):
                code, _, (_argv,), out = run(LABELS, stdout=stdout)
                self.assertEqual((code, out), (2, b""))

    def test_a_failed_ssh_keeps_its_status_and_prints_nothing(self) -> None:
        code, _, _, out = run(LABELS, stdout=b"", returncode=255)
        self.assertEqual((code, out), (255, b""))

    def test_the_workspace_comes_from_the_platform_label_only(self) -> None:
        labels = {key: value for key, value in LABELS.items() if key != "workspace"}
        for broken in (
            labels,
            {**LABELS, "workspace": OTHER},
            {**LABELS, "workspace": f"{WORKSPACE}\n"},
        ):
            with self.subTest(labels=broken.get("workspace")):
                code, _, commands, out = run(broken)
                self.assertEqual((code, commands, out), (2, [], b""))

    def test_the_section_is_what_the_bound_line_prints_first(self) -> None:
        output = forced_output(bound_line(WORKSPACE))
        self.assertEqual(
            output, f"{agent.SECTION.decode()}\n{WORKSPACE}\n".encode() + AGENT
        )
        self.assertEqual(agent.SECTION.decode(), AGENT_SECTION)
        self.assertEqual(agent.WORKSPACE.pattern, rf"ws-{WORKSPACE_ID}")


if __name__ == "__main__":
    unittest.main()
