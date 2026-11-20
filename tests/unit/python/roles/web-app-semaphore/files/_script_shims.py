from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from tests.utils.openbao_stub import OpenBaoStub

from . import PROJECT_ROOT
from ._semaphore_fake import SCRIPTS_DIR, WORKSPACE_ID

COMMIT = "0123456789abcdef0123456789abcdef01234567"
HOST = "203.0.113.10"
HOST_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ2bWvH4yR8xq3k6m0sT9cUeLwPzA1nB5dF7gK2hQ4jX"
)
SHIM = """#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "ansible-inventory":
    print(os.environ.get("SHIM_HOST_VARS", "{}"))
    sys.exit(0)
if name == "git":
    with open(os.environ["SHIM_GIT_RECORD"], "a") as record:
        record.write(json.dumps(args) + "\\n")
    if args[:1] == ["rev-parse"]:
        print(os.environ["SHIM_HEAD"])
    sys.exit(0)
ssh = os.environ.get("ANSIBLE_SSH_ARGS", "")
known = re.search(r"UserKnownHostsFile=(\\S+)", ssh)
control = re.search(r"ControlPath=(\\S+)/cp-%C", ssh)
extra = [a[1:] for a in args if a.startswith("@")]
operation = json.loads(Path(extra[0]).read_text()) if extra else None
agent = os.environ.get("SSH_AUTH_SOCK", "")
listed = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True) if agent else None
key_file = args[args.index("--private-key") + 1] if "--private-key" in args else None
with open(os.environ["SHIM_RECORD"], "a") as record:
    record.write(json.dumps({
        "name": name,
        "argv": args,
        "cwd": os.getcwd(),
        "operation": operation,
        "ssh": ssh,
        "known_hosts": Path(known.group(1)).read_text() if known else None,
        "workdir": control.group(1) if control else None,
        "workdir_exists": bool(control) and Path(control.group(1)).is_dir(),
        "agent_socket": agent,
        "agent_pid": os.environ.get("SSH_AGENT_PID", ""),
        "agent_keys": listed.stdout.splitlines() if listed and listed.returncode == 0 else [],
        "private_key": Path(key_file).read_text() if key_file else None,
    }) + "\\n")
if "-t" in args:
    result = json.loads(os.environ.get("SHIM_RESULTS", "{}")).get(args[args.index("-m") + 1])
    if result is not None:
        tree = Path(args[args.index("-t") + 1])
        tree.mkdir(parents=True, exist_ok=True)
        (tree / args[0]).write_text(json.dumps(result))
"""
HELPERS = (
    "roles/web-app-semaphore/files/python/workspace_ssh_key.py",
    "roles/web-app-semaphore/files/python/lockout_guard.py",
    "roles/web-app-semaphore/files/python/release_host.py",
    "roles/web-app-semaphore/files/python/proof_of_release.py",
    "roles/web-app-semaphore/files/python/transport_guard.py",
    "roles/web-app-semaphore/files/python/inventory_guard.py",
)
PERMIT_KEYS = "prohibit-password"
BAO_ROLE = f"ws-{WORKSPACE_ID}"
TASK_JWT = "task-jwt-of-the-task"
BAO_TOKEN = "bao-token-of-the-task"
KEY_PATH = f"ws-{WORKSPACE_ID}/ssh"
REFERENCE = {"openbao": f"tenant/{KEY_PATH}#private_key"}
AGENT_GONE_SECONDS = 5
KILL_LINE = '\t\tkill "${TASK_AGENT_PID}" 2>/dev/null || stopped=$?\n'
GUARD_CALL = 'python3 -I "${helpers}/lockout_guard.py"'
TRANSPORT_CALL = 'python3 -I "${helpers}/transport_guard.py"'
# Exception: a stand-in that exits without reading its stdin (true) lets
# printf die of SIGPIPE under host.sh's pipefail, so the guard refuses after
# all, under load.
DRAIN = "cat >/dev/null"


def key_pair():
    """Returns:
    A fresh OpenSSH private key and its public line without comment.
    """
    key = ed25519.Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
    )
    return private, public


def host_vars(reference, public, permit=PERMIT_KEYS):
    """Args:
    reference: the value of ``WORKSPACE_SSH_KEY``.
    public: the public key line ``users.root.authorized_keys`` holds, None
        for an empty list.
    permit: ``SYS_SVC_SSHD_PERMIT_ROOT_LOGIN``, None to leave the role
        default in force.

    Returns:
        The host variables ``ansible-inventory --host`` prints, as JSON.
    """
    variables = {
        "ansible_user": "root",
        "WORKSPACE_SSH_KEY": reference,
        "users": {"root": {"authorized_keys": [public] if public else []}},
    }
    if permit is not None:
        variables["SYS_SVC_SSHD_PERMIT_ROOT_LOGIN"] = permit
    return json.dumps(variables)


def workspace_login(case):
    """Args:
    case: the running test case; the OpenBao stub closes with it.

    Returns:
        ``(env, private_key, public_key)``: the workspace, its OpenBao login
        and the host variables of a task whose ``WORKSPACE_SSH_KEY`` names
        the key the stub holds at ``tenant/<KEY_PATH>``.
    """
    private, public = key_pair()
    bao = OpenBaoStub(
        {BAO_TOKEN: [f"tenant/ws-{WORKSPACE_ID}/"]},
        {(BAO_ROLE, TASK_JWT): BAO_TOKEN},
    )
    case.addCleanup(bao.close)
    bao.put(f"tenant/{KEY_PATH}", {"private_key": private})
    env = {
        "WORKSPACE": WORKSPACE_ID,
        "BAO_ADDR": bao.addr,
        "BAO_CACERT": bao.cafile,
        "BAO_ROLE": BAO_ROLE,
        "SEMAPHORE_JWT": TASK_JWT,
        "SHIM_HOST_VARS": host_vars(REFERENCE, public),
    }
    return env, private, public


def agent_alive(pid):
    """Args:
    pid: the process id of an SSH agent.

    Returns:
        Whether the process still runs; a zombie counts as gone.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(
            encoding="utf-8"
        )  # nocheck: cache-read procfs
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def agent_gone(pid):
    """Args:
    pid: the process id of an SSH agent.

    Returns:
        Whether the process ended within ``AGENT_GONE_SECONDS``.
    """
    deadline = time.monotonic() + AGENT_GONE_SECONDS
    while agent_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def _planted(tmp, line, replacement):
    planted = Path(tmp) / "planted"
    shutil.copytree(SCRIPTS_DIR, planted)
    lib = planted / "lib.sh"
    text = lib.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    if line not in text:
        raise AssertionError(f"lib.sh no longer holds {line.strip()}")
    lib.write_text(text.replace(line, replacement), encoding="utf-8")
    return planted


def planted_without_kill(tmp):
    """Args:
    tmp: a scratch directory.

    Returns:
        A copy of the scripts folder whose ``lib.sh`` never kills the task agent.
    """
    return _planted(tmp, KILL_LINE, "\t\t:\n")


def planted_without_guard(tmp):
    """Args:
    tmp: a scratch directory.

    Returns:
        A copy of the scripts folder whose ``lib.sh`` never runs the lock-out guard.
    """
    return _planted(tmp, GUARD_CALL, DRAIN)


def planted_without_transport_guard(tmp):
    """Args:
    tmp: a scratch directory.

    Returns:
        A copy of the scripts folder whose ``lib.sh`` never runs the transport guard.
    """
    return _planted(tmp, TRANSPORT_CALL, DRAIN)


class ScriptRunner:
    """Args:
    roles: the role names the fake core tree holds.
    """

    def __init__(self, roles=("web-app-wiki",)):
        self.scratch = tempfile.TemporaryDirectory()
        self.tmp = Path(self.scratch.name)
        self.bin = self.tmp / "bin"
        self.src = self.tmp / "src"
        self.home = self.tmp / "home"
        self.checkout = self.tmp / "checkout"
        for directory in (self.bin, self.home, self.checkout):
            directory.mkdir()
        for role in roles:
            (self.src / "roles" / role).mkdir(parents=True)
        for name in HELPERS:
            helper = self.src / name
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.symlink_to(PROJECT_ROOT / name)
        (self.src / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
        for name in (
            "git",
            "infinito",
            "ansible",
            "ansible-playbook",
            "ansible-inventory",
        ):
            shim = self.bin / name
            shim.write_text(SHIM, encoding="utf-8")
            shim.chmod(0o755)
        (self.checkout / "devices.yml").write_text("all: {}\n", encoding="utf-8")
        self.record = self.tmp / "record.jsonl"
        self.git_record = self.tmp / "git.jsonl"

    def cleanup(self):
        self.scratch.cleanup()

    def run(self, script, env, args=(), directory=SCRIPTS_DIR):
        """Args:
        script: the script name under ``directory``.
        env: the task environment beside PATH and HOME.
        args: the command line.
        directory: the folder holding the script, ``files/shell/repository``
            unless a test runs a planted copy.

        Returns:
            The completed process.
        """
        self.record.unlink(missing_ok=True)
        self.git_record.unlink(missing_ok=True)
        full = {
            "SHIM_GIT_RECORD": str(self.git_record),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "INFINITO_SRC_DIR": str(self.src),
            "SHIM_RECORD": str(self.record),
            "SHIM_HEAD": env.get("INVENTORY_COMMIT", COMMIT),
            **env,
        }
        return subprocess.run(
            ["bash", str(directory / script), *args],
            cwd=self.checkout,
            env=full,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self):
        """Returns:
        Every call of ``infinito`` or ``ansible`` the last run made.
        """
        if not self.record.exists():
            return []
        text = self.record.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return [json.loads(line) for line in text.splitlines()]

    def git_calls(self):
        """Returns:
        The argument lists of every ``git`` call the last run made.
        """
        if not self.git_record.exists():
            return []
        text = self.git_record.read_text(encoding="utf-8")  # nocheck: cache-read
        return [json.loads(line) for line in text.splitlines()]


def deploy_env(**overrides):
    """Args:
    overrides: variables to set; None drops one.

    Returns:
        The environment of a valid workspace deploy.
    """
    env = {
        "WORKSPACE": WORKSPACE_ID,
        "WORKSPACE_DNS_ZONE": "ws.example.org",
        "WORKSPACE_TARGETS": f"{HOST}:22",
        "SALES_ORDER": "SO-1001",
        "LINE": "1",
        "HOST": HOST,
        "HOST_KEY": HOST_KEY,
        "ROLES": "web-app-wiki",
        "DNS_LABEL": "wiki",
        "INVENTORY_COMMIT": COMMIT,
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def host_env(**overrides):
    """Args:
    overrides: variables to set; None drops one.

    Returns:
        The environment of a valid ``update`` or ``backup``.
    """
    env = {
        "WORKSPACE_TARGETS": f"{HOST}:22",
        "HOST": HOST,
        "HOST_KEY": HOST_KEY,
        "INVENTORY_COMMIT": COMMIT,
        "WORKSPACE_INVENTORY_FILE": "devices.yml",
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}
