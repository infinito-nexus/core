"""The community.docker docker connection, asking the Docker CLI for its version at the start of a run.

The stock plugin builds a fresh connection in every forked worker, and with a
remote user set it runs ``docker version`` twice before every module run (the
first probe never matches a current Docker). This subclass keeps the answer in
a file under the run's ``DEFAULT_LOCAL_TMP``, which every worker inherits from
the ``ansible-playbook`` process and which Ansible removes when the run ends,
so only the workers that start before the first answer is written pay for the
version query. The file is replaced atomically, so a concurrent writer never
leaves a partial answer. Everything else (user, become, file transfer,
timeouts, environment) is the stock plugin's.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ansible import constants
from ansible_collections.community.docker.plugins.connection.docker import (
    Connection as DockerConnection,
)

DOCUMENTATION = r"""
name: docker_cached
short_description: Run tasks in docker containers, with the Docker version cached per run
description:
  - The community.docker docker connection, except that the Docker CLI version is queried at the start
    of an ansible-playbook run and shared by every forked worker that starts after the first answer.
options:
  remote_addr:
    description:
      - The name of the container you want to access.
    default: inventory_hostname
    vars:
      - name: inventory_hostname
      - name: ansible_host
      - name: ansible_docker_host
  remote_user:
    description:
      - The user to execute as inside the container.
    vars:
      - name: ansible_user
      - name: ansible_docker_user
    ini:
      - section: defaults
        key: remote_user
    env:
      - name: ANSIBLE_REMOTE_USER
    cli:
      - name: user
    keyword:
      - name: remote_user
  docker_extra_args:
    description:
      - Extra arguments to pass to the docker command line.
    default: ''
    vars:
      - name: ansible_docker_extra_args
    ini:
      - section: docker_connection
        key: extra_cli_args
  container_timeout:
    default: 10
    description:
      - Controls how long we can wait to access reading output from the container once execution started.
    env:
      - name: ANSIBLE_TIMEOUT
      - name: ANSIBLE_DOCKER_TIMEOUT
    ini:
      - key: timeout
        section: defaults
      - key: timeout
        section: docker_connection
    vars:
      - name: ansible_docker_timeout
    cli:
      - name: timeout
    type: integer
  extra_env:
    description:
      - Extra environment variables to set when running commands in the Docker container.
    vars:
      - name: ansible_docker_extra_env
    type: dict
  working_dir:
    description:
      - The directory inside the container to run commands in.
    env:
      - name: ANSIBLE_DOCKER_WORKING_DIR
    ini:
      - key: working_dir
        section: docker_connection
    vars:
      - name: ansible_docker_working_dir
    type: string
  privileged:
    description:
      - Whether commands should be run with extended privileges.
    env:
      - name: ANSIBLE_DOCKER_PRIVILEGED
    ini:
      - key: privileged
        section: docker_connection
    vars:
      - name: ansible_docker_privileged
    type: boolean
    default: false
"""


class Connection(DockerConnection):
    transport = "docker_cached"

    def _version_cache_path(self) -> Path:
        scope = "\0".join(
            [self.docker_cmd, *self._docker_args, os.environ.get("DOCKER_HOST") or ""]
        )
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
        return Path(constants.DEFAULT_LOCAL_TMP) / f"docker-version-{digest}"

    def _get_docker_version(self) -> str:
        path = self._version_cache_path()
        try:
            cached = path.read_text(
                encoding="utf-8"  # nocheck: cache-read (per-run file the first worker writes)
            ).strip()
        except FileNotFoundError:
            cached = ""
        if cached:
            return cached
        version = super()._get_docker_version()
        staging = path.with_name(f"{path.name}.{os.getpid()}")
        staging.write_text(version, encoding="utf-8")
        staging.replace(path)
        return version
