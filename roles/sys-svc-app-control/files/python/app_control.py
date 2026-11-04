#!/usr/bin/env python3
"""Pause and resume the applications a deploy put under app control.

Usage:
    app-control --config FILE stop APPLICATION_ID|all
    app-control --config FILE start APPLICATION_ID|all
    app-control --config FILE reconcile
    app-control --config FILE ssh

Args:
    --config: JSON naming ``compositions`` (the parent of every compose
        instance), ``registry_file`` and ``state_file`` (the file names of the
        record and of the state marker inside an instance), ``paused_apps``
        (the directory nginx tests for a paused project), ``compose`` (the
        compose wrapper), ``binary`` (the installed path of this command),
        ``health_service`` (the webserver health sweep unit run after a stop
        or start, skipped where it is not installed) and
        ``health_delay_seconds`` (how long after the last stop or start that
        sweep runs, so a resumed application answers first).
    stop/start: pause or resume one application whose registry sets
        ``control``, or every such application of this host with ``all``.
    reconcile: apply the persisted state of every registered application; an
        application without a state marker is put into its declared ``status``.
    ssh: forced command of the restricted account; accepts only
        ``app-control stop|start <target>`` in ``SSH_ORIGINAL_COMMAND`` and
        re-executes itself as root through ``sudo -n``.

Output:
    One ``[application_id] ...`` line per application; ``CHANGED`` marks a
    state change. Exit code 1 when any application failed or the health sweep
    could not be scheduled, 2 when the request was refused.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from app_control_argv import (
    compose_argv,
    scale_to_zero_argv,
    stack_deploy_argv,
    stack_services_argv,
)

COMMAND = "app-control"
ACTIONS = ("stop", "start")
STATES = ("started", "stopped")
MODES = ("compose", "swarm")
ALL = "all"
TARGET = re.compile(r"all|[a-z0-9]+(?:-[a-z0-9]+)*")
HEALTH_REFRESH_UNIT = "app-control-health-refresh"


class RefusedError(Exception):
    """A request app-control does not carry out."""


def load_config(path):
    """Return the parsed configuration.

    Args:
        path: the JSON file the deploy writes.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def registries(config):
    """Return every registry of this host, keyed by application id.

    Args:
        config: the parsed configuration.
    """
    found = {}
    pattern = f"*/{config['registry_file']}"
    for path in sorted(Path(config["compositions"]).glob(pattern)):
        registry = json.loads(path.read_text(encoding="utf-8"))
        found[registry["application_id"]] = registry
    return found


def controlled(registry):
    """Return whether an application is under app control.

    Args:
        registry: the record its deploy wrote.
    """
    control = registry["control"]
    if not isinstance(control, bool):
        raise RefusedError(
            f"{registry['application_id']} declares control {control!r}, not a boolean"
        )
    return control


def marker_path(config, registry):
    """Return the path of the state marker of an application.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
    """
    return Path(registry["instance"]) / config["state_file"]


def projection_path(config, registry):
    """Return the path nginx tests to answer an application with the paused page.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
    """
    return Path(config["paused_apps"]) / registry["project"]


def read_state(config, registry):
    """Return the persisted state of an application, None without a marker.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
    """
    path = marker_path(config, registry)
    if not path.exists():
        return None
    state = path.read_text(encoding="utf-8").strip()
    if state not in STATES:
        raise RefusedError(
            f"{path} holds {state!r}, expected one of {', '.join(STATES)}"
        )
    return state


def desired_state(marker, status):
    """Return the state an application has to end in.

    Args:
        marker: the persisted state, None when no marker exists.
        status: the ``status`` the application declares for its creation.
    """
    if status not in STATES:
        raise RefusedError(f"status {status!r} is not one of {', '.join(STATES)}")
    return status if marker is None else marker


def select(found, target):
    """Return the registries a request acts on, in application id order.

    Args:
        found: every registry of this host, keyed by application id.
        target: an application id, or ``all`` for every controlled one.
    """
    if target == ALL:
        return [found[name] for name in sorted(found) if controlled(found[name])]
    if target not in found:
        raise RefusedError(f"{target} is not deployed on this host")
    if not controlled(found[target]):
        raise RefusedError(f"{target} is not under app control")
    return [found[target]]


def ssh_request(original):
    """Return the ``(action, target)`` a forced-command session asks for.

    Args:
        original: the ``SSH_ORIGINAL_COMMAND`` of the session.
    """
    words = original.split()
    if (
        len(words) != 3
        or words[0] != COMMAND
        or words[1] not in ACTIONS
        or not TARGET.fullmatch(words[2])
    ):
        raise RefusedError(
            f"only '{COMMAND} stop|start <application>|all' is permitted"
        )
    return words[1], words[2]


def ssh_session(environ):
    """Return the ``(action, target)`` of a forced-command SSH session.

    Args:
        environ: the process environment of the session.
    """
    if "SSH_ORIGINAL_COMMAND" not in environ:
        raise RefusedError("interactive sessions are not permitted")
    return ssh_request(environ["SSH_ORIGINAL_COMMAND"])


def require_root(command, euid):
    """Refuse ``command`` unless the process runs as root.

    Args:
        command: the app-control subcommand.
        euid: ``os.geteuid`` or a stand-in.
    """
    if euid() != 0:
        raise RefusedError(f"{command} has to run as root")


def mode_of(registry):
    """Return the deploy mode of an application.

    Args:
        registry: the record its deploy wrote.
    """
    mode = registry["mode"]
    if mode not in MODES:
        raise RefusedError(f"{registry['application_id']} has mode {mode!r}")
    return mode


def timer_present(run, unit):
    """Return whether a systemd unit is installed on this host.

    Args:
        run: ``subprocess.run`` or a stand-in.
        unit: the unit name.
    """
    listed = run(
        ["systemctl", "list-unit-files", "--no-legend", "--plain", unit],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(listed.stdout.strip())


def write_state(config, registry, state):
    """Persist a state, then project it for nginx.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
        state: ``started`` or ``stopped``.
    """
    marker = marker_path(config, registry)
    pending = marker.with_name(f"{marker.name}.tmp")
    pending.write_text(f"{state}\n", encoding="utf-8")
    pending.replace(marker)
    projection = projection_path(config, registry)
    if state == "stopped":
        projection.touch(mode=0o644)
    else:
        projection.unlink(missing_ok=True)


def forget(config, registry):
    """Drop the state and its projection of an application outside app control.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
    """
    marker_path(config, registry).unlink(missing_ok=True)
    projection_path(config, registry).unlink(missing_ok=True)


def pause(config, registry, run):
    """Leave no running instance of an application.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
        run: ``subprocess.run`` or a stand-in.
    """
    mode = mode_of(registry)
    write_state(config, registry, "stopped")
    if timer_present(run, registry["timer"]):
        run(["systemctl", "stop", registry["timer"]], check=True)
    if mode == "compose":
        run(compose_argv(config, registry, "down"), check=True)
        return
    listed = run(
        stack_services_argv(registry), capture_output=True, text=True, check=True
    )
    services = listed.stdout.split()
    if services:
        run(scale_to_zero_argv(services), check=True)


def resume(config, registry, run):
    """Bring an application back to its declared state.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
        run: ``subprocess.run`` or a stand-in.
    """
    if mode_of(registry) == "compose":
        run(compose_argv(config, registry, "up", "-d"), check=True)
    else:
        run(stack_deploy_argv(registry), cwd=registry["instance"], check=True)
    if timer_present(run, registry["timer"]):
        run(["systemctl", "start", registry["timer"]], check=True)
    write_state(config, registry, "started")


def act(config, action, target, run):
    """Carry out ``stop`` or ``start`` and return the application ids that failed.

    Args:
        config: the parsed configuration.
        action: ``stop`` or ``start``.
        target: an application id, or ``all``.
        run: ``subprocess.run`` or a stand-in.
    """
    failed = []
    state = "stopped" if action == "stop" else "started"
    for registry in select(registries(config), target):
        application_id = registry["application_id"]
        try:
            if action == "stop":
                pause(config, registry, run)
            else:
                resume(config, registry, run)
        except (RefusedError, subprocess.CalledProcessError, OSError) as error:
            print(f"[{application_id}] FAILED {error}", file=sys.stderr)
            failed.append(application_id)
            continue
        print(f"[{application_id}] CHANGED {state}")
    return failed


def refresh_health(config, run):
    """Schedule one webserver health sweep after the last stop or start.

    Args:
        config: the parsed configuration; ``health_service`` names the sweep
            unit and ``health_delay_seconds`` the wait before it runs.
        run: ``subprocess.run`` or a stand-in.

    Returns:
        The error that kept the sweep from being scheduled, None when it was
        scheduled or when the unit is not installed on this host.
    """
    unit = config["health_service"]
    if not timer_present(run, unit):
        return None
    run(["systemctl", "stop", f"{HEALTH_REFRESH_UNIT}.timer"], check=False)
    try:
        run(
            [
                "systemd-run",
                f"--unit={HEALTH_REFRESH_UNIT}",
                f"--on-active={int(config['health_delay_seconds'])}",
                "--timer-property=AccuracySec=1s",
                "--timer-property=RemainAfterElapse=no",
                "--collect",
                "systemctl",
                "start",
                "--no-block",
                unit,
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as error:
        return str(error)
    return None


def reconcile(config, run):
    """Apply the persisted state of every application and return the ids that failed.

    Args:
        config: the parsed configuration.
        run: ``subprocess.run`` or a stand-in.
    """
    failed = []
    for application_id, registry in sorted(registries(config).items()):
        try:
            if not controlled(registry):
                forget(config, registry)
                continue
            marker = read_state(config, registry)
            state = desired_state(marker, registry["status"])
            if state == "stopped":
                pause(config, registry, run)
                print(f"[{application_id}] CHANGED stopped")
                continue
            changed = marker is None or projection_path(config, registry).exists()
            write_state(config, registry, "started")
            print(f"[{application_id}] {'CHANGED' if changed else 'ok'} started")
        except (RefusedError, subprocess.CalledProcessError, OSError) as error:
            print(f"[{application_id}] FAILED {error}", file=sys.stderr)
            failed.append(application_id)
    return failed


@contextlib.contextmanager
def locked(config):
    """Hold the host-wide app-control lock.

    Args:
        config: the parsed configuration.
    """
    descriptor = os.open(config["compositions"], os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def parse_args(argv):
    """Return the parsed command line.

    Args:
        argv: the command line arguments.
    """
    parser = argparse.ArgumentParser(prog=COMMAND, description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ACTIONS:
        commands.add_parser(action).add_argument("target")
    commands.add_parser("reconcile")
    commands.add_parser("ssh")
    return parser.parse_args(argv)


def main(
    argv,
    run=subprocess.run,
    environ=os.environ,
    execvp=os.execvp,
    euid=os.geteuid,
):
    """Run app-control and return its exit code.

    Args:
        argv: the command line arguments.
        run: ``subprocess.run`` or a stand-in.
        environ: the process environment.
        execvp: ``os.execvp`` or a stand-in.
        euid: ``os.geteuid`` or a stand-in.
    """
    options = parse_args(argv)
    config = load_config(options.config)
    try:
        if options.command == "ssh":
            action, target = ssh_session(environ)
            escalated = [config["binary"], "--config", options.config, action, target]
            execvp("sudo", ["sudo", "-n", *escalated])
            return 0
        require_root(options.command, euid)
        refresh_error = None
        with locked(config):
            if options.command == "reconcile":
                failed = reconcile(config, run)
            else:
                failed = act(config, options.command, options.target, run)
                refresh_error = refresh_health(config, run)
    except RefusedError as error:
        print(f"{COMMAND}: refused: {error}", file=sys.stderr)
        return 2
    if refresh_error:
        print(
            f"{COMMAND}: health sweep not scheduled: {refresh_error}", file=sys.stderr
        )
    if failed:
        print(f"FAILED applications: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 1 if refresh_error else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
