#!/usr/bin/env python3
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ACTIVE_AGENT_STATES = ("Active", "Active/Local")
DEFAULT_COLLECTOR_GRACE = 5
DEFAULT_WAIT_FILE = "/var/ossec/queue/sockets/.wait"
AGENT_LINE = re.compile(r"^\s*ID: (\d+), Name: (.+?), IP: .*, (\S.*?)\s*$")
KEEPALIVE_LINE = re.compile(r"^\s*Last keep alive:\s+(\d+)\s*$", re.MULTILINE)
STATE_LINE = re.compile(r"^(\w+)='(.*)'$")


def parse_state(text):
    """Return the key='value' pairs of wazuh-agentd.state.

    Args:
        text: the state file's content.
    """
    return {
        match.group(1): match.group(2)
        for match in (STATE_LINE.match(line.strip()) for line in text.splitlines())
        if match
    }


def evaluate_host(service_active, agentd_age, state, now, threshold):
    """Return the host agent's problems, empty when it is healthy.

    Args:
        service_active: whether the agent's systemd unit is active.
        agentd_age: seconds since wazuh-agentd started, None when it is not running.
        state: parsed wazuh-agentd.state, None when the file is missing.
        now: the current local time.
        threshold: seconds a disconnect is tolerated, and the grace after wazuh-agentd starts.
    """
    if not service_active:
        return ["the agent service is not active"]
    if agentd_age is None:
        return ["the agent service is active, but wazuh-agentd is not running"]
    if agentd_age < threshold:
        return []
    if state is None:
        return ["wazuh-agentd has written no state file"]
    if state.get("status") == "connected":
        return []
    try:
        ack_age = int(
            (
                now
                - datetime.strptime(
                    state.get("last_ack", ""), "%Y-%m-%d %H:%M:%S"
                ).astimezone()
            ).total_seconds()
        )
    except ValueError:
        ack_age = None
    if ack_age is not None and ack_age < threshold:
        return []
    ack = "never" if ack_age is None else f"{ack_age} s ago"
    return [
        (
            f"wazuh-agentd is {state.get('status', 'unknown')}: last manager ACK {ack} "
            f"(threshold {threshold} s), {state.get('msg_buffer', '?')} events buffered"
        )
    ]


def evaluate_manager(listing, keepalives, since_change, now_epoch, threshold):
    """Return the manager's problems with its registered agents, empty when all are Active.

    Args:
        listing: output of agent_control -l, None when the manager is unreachable.
        keepalives: agent id to its last keepalive epoch from agent_control -i, None for never.
        since_change: seconds since the manager container last started or stopped, None when unknown.
        now_epoch: the current time in epoch seconds.
        threshold: seconds a disconnect is tolerated, and the grace after the manager starts or stops.
    """
    if since_change is not None and since_change < threshold:
        return []
    if listing is None:
        return ["the Wazuh manager is unreachable"]
    problems = []
    for agent_id, name, status in parse_agents(listing):
        if agent_id == "000" or status in ACTIVE_AGENT_STATES:
            continue
        keepalive = keepalives.get(agent_id)
        if keepalive is not None and now_epoch - keepalive < threshold:
            continue
        seen = "never" if keepalive is None else f"{int(now_epoch - keepalive)} s ago"
        problems.append(
            f"agent {agent_id} ({name}) is {status}: last keepalive {seen} (threshold {threshold} s)"
        )
    return problems


def evaluate_clock(ntp_synchronized):
    """Return the clock problem, empty when the host clock is synchronized.

    Args:
        ntp_synchronized: timedatectl's NTPSynchronized value, None when it could not be read.
    """
    if ntp_synchronized == "yes":
        return []
    return [
        f"the host clock is not synchronized (NTPSynchronized={ntp_synchronized or 'unreadable'}); Wazuh event times cannot be trusted"
    ]


def evaluate_collector(collector_state, agent_locked):
    """Return the collector problem, empty unless it is frozen while the agent is online.

    Args:
        collector_state: wazuh-logcollector's process state letter, None when it is not running.
        agent_locked: whether wazuh-agentd's offline lock (queue/sockets/.wait) exists.
    """
    if collector_state == "T" and not agent_locked:
        return [
            "wazuh-logcollector is frozen although the agent is online; no log line is collected until it is resumed"
        ]
    return []


def collector_state(run_dir):
    for pid_file in glob.glob(str(Path(run_dir) / "wazuh-logcollector-*.pid")):
        pid = pid_file.rsplit("-", 1)[1].split(".", 1)[0]
        try:
            return (
                Path(f"/proc/{pid}/stat")
                .read_text(encoding="ascii")
                .rsplit(")", 1)[1]
                .split()[0]
            )
        except (OSError, IndexError):
            continue
    return None


def parse_agents(listing):
    """Return (id, name, status) of every agent line in agent_control -l output.

    Args:
        listing: output of agent_control -l.
    """
    return [
        match.groups() for match in map(AGENT_LINE.match, listing.splitlines()) if match
    ]


def process_age(pid):
    start_ticks = int(
        Path(f"/proc/{pid}/stat")
        .read_text(encoding="ascii")
        .rsplit(")", 1)[1]
        .split()[19]
    )
    uptime = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    return uptime - start_ticks / os.sysconf("SC_CLK_TCK")


def agentd_age(run_dir):
    for pid_file in glob.glob(str(Path(run_dir) / "wazuh-agentd-*.pid")):
        pid = pid_file.rsplit("-", 1)[1].split(".", 1)[0]
        try:
            return process_age(pid)
        except (OSError, ValueError, IndexError):
            continue
    return None


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def epoch(timestamp):
    return (
        datetime.fromisoformat(timestamp.strip()[:26].rstrip("Z"))
        .replace(tzinfo=UTC)
        .timestamp()
    )


def manager_problems(container, threshold):
    inspect = run(
        [
            "container",
            "inspect",
            "-f",
            "{{.State.Running}} {{.State.StartedAt}} {{.State.FinishedAt}}",
            container,
        ]
    )
    since_change = None
    if inspect:
        running, started, finished = inspect.split()
        since_change = time.time() - epoch(started if running == "true" else finished)
    listing = run(
        ["container", "exec", container, "/var/ossec/bin/agent_control", "-l"]
    )
    keepalives = {}
    for agent_id, _name, status in parse_agents(listing or ""):
        if agent_id == "000" or status in ACTIVE_AGENT_STATES:
            continue
        detail = (
            run(
                [
                    "container",
                    "exec",
                    container,
                    "/var/ossec/bin/agent_control",
                    "-i",
                    agent_id,
                ]
            )
            or ""
        )
        match = KEEPALIVE_LINE.search(detail)
        keepalives[agent_id] = int(match.group(1)) if match else None
    return evaluate_manager(listing, keepalives, since_change, time.time(), threshold)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the Wazuh agent and the host clock on this host and, on the manager host, every registered agent."
    )
    parser.add_argument("--service", required=True, help="systemd unit of the agent")
    parser.add_argument(
        "--run-dir", required=True, help="the agent's var/run directory"
    )
    parser.add_argument(
        "--threshold",
        required=True,
        type=int,
        help="seconds of tolerated disconnect and of grace after a start",
    )
    parser.add_argument(
        "--manager",
        help="manager container name; checks every registered agent when set",
    )
    # Exception: defaults equal the role's vars so units rendered before the collector freeze keep working without both args.
    parser.add_argument(
        "--wait-file",
        default=DEFAULT_WAIT_FILE,
        help="wazuh-agentd's offline lock file",
    )
    parser.add_argument(
        "--collector-grace",
        default=DEFAULT_COLLECTOR_GRACE,
        type=int,
        help="seconds a frozen collector may lag behind the lock",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    try:
        state = parse_state(
            (Path(args.run_dir) / "wazuh-agentd.state").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        state = None
    service_active = (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", args.service], check=False
        ).returncode
        == 0
    )
    problems = evaluate_host(
        service_active,
        agentd_age(args.run_dir),
        state,
        datetime.now().astimezone(),
        args.threshold,
    )
    ntp = run(["timedatectl", "show", "--property=NTPSynchronized", "--value"])
    problems += evaluate_clock(ntp.strip() if ntp is not None else None)
    if evaluate_collector(collector_state(args.run_dir), Path(args.wait_file).exists()):
        time.sleep(args.collector_grace)
        problems += evaluate_collector(
            collector_state(args.run_dir), Path(args.wait_file).exists()
        )
    if args.manager:
        problems += manager_problems(args.manager, args.threshold)

    for problem in problems:
        print(f"❌ {problem}")
    if problems:
        sys.exit(1)
    print(f"✅ No Wazuh agent problem beyond the {args.threshold} s threshold")


if __name__ == "__main__":
    main()
