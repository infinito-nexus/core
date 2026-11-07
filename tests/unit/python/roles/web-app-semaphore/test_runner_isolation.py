"""The dedicated runner runs every template without the Docker socket, root or a key."""

from __future__ import annotations

import copy
import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SERVER_ENV = ROLE / "templates" / "env.j2"
RUNNER_ENV = ROLE / "templates" / "env" / "task-runner.j2"
DOCKERFILE = ROLE / "files" / "runner" / "Dockerfile"

RUNNER = "task-runner"
TOKEN_VOLUME = "semaphore_runner_token"
REMOTE_RUNNER_KEY = "SEMAPHORE_USE_REMOTE_RUNNER"
REMOTE_RUNNER_LINE = f"{REMOTE_RUNNER_KEY}=true"
RUNNER_USER = "${SEMAPHORE_RUNNER_UID}:${SEMAPHORE_RUNNER_GID}"
RUNNER_IDS = (("SEMAPHORE_RUNNER_UID", "uid"), ("SEMAPHORE_RUNNER_GID", "gid"))
BLOCK_START = "{% set service_name = SEMAPHORE_RUNNER_SERVICE %}"
BLOCK_END = "{{ lookup('compose_volumes') }}"
BLOCK_FORBIDDEN = (
    "docker.sock",
    "privileged",
    "user:",
    "volumes:",
    "cap_add",
    "network_mode",
    "pid:",
)
ENV_FORBIDDEN = ("PRIVATE_KEY", "SSH_KEY", "ssh_key", "BEGIN OPENSSH")
GUARD_OPEN = "{% if SEMAPHORE_DEPLOY_ENABLED | bool %}"
GUARD_CLOSE = "{% endif %}"
SOCKET_VOLUME = "    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n"
_OPEN = re.compile(r"{%-?\s*if\b")
_CLOSE = re.compile(r"{%-?\s*endif\b")


def _text(path) -> str:
    return read_text(str(path))


def _yaml(relative: str):
    return load_yaml_str(_text(ROLE / relative))


def remote_runner_findings(env: str) -> list[str]:
    """Return why the server could still run a template itself.

    Args:
        env: the server's ``templates/env.j2``.
    """
    lines = env.splitlines()
    settings = [line for line in lines if line.startswith(f"{REMOTE_RUNNER_KEY}=")]
    if settings != [REMOTE_RUNNER_LINE]:
        return [f"expected exactly {REMOTE_RUNNER_LINE}, found {settings}"]
    above = "\n".join(lines[: lines.index(REMOTE_RUNNER_LINE)])
    if len(_OPEN.findall(above)) != len(_CLOSE.findall(above)):
        return [f"{REMOTE_RUNNER_LINE} is set only under a condition"]
    return []


def runner_volume_findings(volumes: dict) -> list[str]:
    """Return every mount of the runner beyond its runner token.

    Args:
        volumes: the role's ``meta/volumes.yml``.
    """
    mounted = sorted(
        name
        for name, entry in volumes.items()
        if any(mount.get("service") == RUNNER for mount in entry.get("mounts", []))
    )
    if mounted != [TOKEN_VOLUME]:
        return [f"{RUNNER} mounts {mounted}, expected only {TOKEN_VOLUME}"]
    if volumes[TOKEN_VOLUME].get("type") != "secret":
        return [f"{TOKEN_VOLUME} is no secret"]
    return []


def runner_block_findings(compose: str) -> list[str]:
    """Return every literal of the runner service that widens its reach.

    Args:
        compose: the role's ``templates/compose.yml.j2``.
    """
    block = compose[compose.index(BLOCK_START) : compose.index(BLOCK_END)]
    return [
        f"the {RUNNER} service sets {token}"
        for token in BLOCK_FORBIDDEN
        if token in block
    ]


def runner_user_findings(dockerfile: str, variables: dict, volumes: dict) -> list[str]:
    """Return why the runner could run as root.

    Args:
        dockerfile: the runner's Dockerfile.
        variables: the role's ``vars/main.yml``.
        volumes: the role's ``meta/volumes.yml``.
    """
    users = re.findall(r"(?m)^USER\s+(\S+)\s*$", dockerfile)
    if not users or users[-1] != RUNNER_USER:
        return [f"the last USER is {users[-1:]}, expected {RUNNER_USER}"]
    findings = []
    for name, field in RUNNER_IDS:
        source = f"lookup('volume', application_id, '{TOKEN_VOLUME}').{field}"
        if source not in str(variables.get(name)):
            findings.append(f"{name} does not read the {field} of {TOKEN_VOLUME}")
        value = volumes[TOKEN_VOLUME].get(field)
        if not isinstance(value, int) or value <= 0:
            findings.append(
                f"the {field} of {TOKEN_VOLUME} is {value!r}, not an unprivileged id"
            )
    return findings


def runner_env_findings(env: str) -> list[str]:
    """Return every key material the runner environment carries.

    Args:
        env: the runner's ``templates/env/task-runner.j2``.
    """
    return [
        f"the runner env carries {token}" for token in ENV_FORBIDDEN if token in env
    ]


class TestRunnerIsolation(unittest.TestCase):
    def setUp(self):
        self.server_env = _text(SERVER_ENV)
        self.runner_env = _text(RUNNER_ENV)
        self.compose = _text(ROLE / ROLE_FILE_TEMPL_COMPOSE)
        self.dockerfile = _text(DOCKERFILE)
        self.variables = _yaml(ROLE_FILE_VARS_MAIN)
        self.volumes = _yaml(ROLE_FILE_META_VOLUMES)

    def test_the_server_hands_every_template_to_the_runner(self):
        self.assertEqual(remote_runner_findings(self.server_env), [])

    def test_the_runner_mounts_only_its_token(self):
        self.assertEqual(runner_volume_findings(self.volumes), [])

    def test_the_runner_service_adds_no_mount_privilege_or_user(self):
        self.assertEqual(runner_block_findings(self.compose), [])

    def test_the_runner_runs_as_an_unprivileged_user(self):
        self.assertEqual(
            runner_user_findings(self.dockerfile, self.variables, self.volumes), []
        )

    def test_the_runner_env_carries_no_key(self):
        self.assertEqual(runner_env_findings(self.runner_env), [])

    def test_negative_control_a_local_runner_is_reported(self):
        drifted = self.server_env.replace(
            REMOTE_RUNNER_LINE, f"{REMOTE_RUNNER_KEY}=false"
        )
        self.assertNotEqual(drifted, self.server_env)
        self.assertTrue(remote_runner_findings(drifted))

    def test_negative_control_a_conditional_remote_runner_is_reported(self):
        guarded = f"{GUARD_OPEN}\n{REMOTE_RUNNER_LINE}\n{GUARD_CLOSE}"
        drifted = self.server_env.replace(REMOTE_RUNNER_LINE, guarded)
        self.assertEqual(
            remote_runner_findings(drifted),
            [f"{REMOTE_RUNNER_LINE} is set only under a condition"],
        )

    def test_negative_control_a_docker_socket_mount_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["docker_socket"] = {
            "type": "bind",
            "source": "/var/run/docker.sock",
            "mounts": [{"service": RUNNER, "target": "/var/run/docker.sock"}],
        }
        self.assertEqual(len(runner_volume_findings(volumes)), 1)

    def test_negative_control_a_literal_socket_volume_is_reported(self):
        drifted = self.compose.replace(BLOCK_END, SOCKET_VOLUME + BLOCK_END)
        self.assertEqual(
            runner_block_findings(drifted),
            [
                f"the {RUNNER} service sets docker.sock",
                f"the {RUNNER} service sets volumes:",
            ],
        )

    def test_negative_control_a_root_user_is_reported(self):
        drifted = self.dockerfile.replace("ENTRYPOINT", "USER root\nENTRYPOINT", 1)
        self.assertEqual(
            runner_user_findings(drifted, self.variables, self.volumes),
            [f"the last USER is ['root'], expected {RUNNER_USER}"],
        )

    def test_negative_control_a_root_uid_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes[TOKEN_VOLUME]["uid"] = 0
        self.assertEqual(
            runner_user_findings(self.dockerfile, self.variables, volumes),
            [f"the uid of {TOKEN_VOLUME} is 0, not an unprivileged id"],
        )

    def test_negative_control_a_key_in_the_runner_env_is_reported(self):
        drifted = f"{self.runner_env}SEMAPHORE_APP_CONTROL_PRIVATE_KEY=x\n"
        self.assertEqual(
            runner_env_findings(drifted), ["the runner env carries PRIVATE_KEY"]
        )


if __name__ == "__main__":
    unittest.main()
