#!/usr/bin/env python3
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ACTIVE_AGENT_STATES = ("Active", "Active/Local")
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
        ack_age = int((now - datetime.strptime(state.get("last_ack", ""), "%Y-%m-%d %H:%M:%S")).total_seconds())
    except ValueError:
        ack_age = None
    if ack_age is not None and ack_age < threshold:
        return []
    ack = "never" if ack_age is None else f"{ack_age} s ago"
    return [
        f"wazuh-agentd is {state.get('status', 'unknown')}: last manager ACK {ack} "
        f"(threshold {threshold} s), {state.get('msg_buffer', '?')} events buffered"
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
        problems.append(f"agent {agent_id} ({name}) is {status}: last keepalive {seen} (threshold {threshold} s)")
    return problems


def parse_agents(listing):
    """Return (id, name, status) of every agent line in agent_control -l output.

    Args:
        listing: output of agent_control -l.
    """
    return [match.groups() for match in map(AGENT_LINE.match, listing.splitlines()) if match]


def process_age(pid):
    with open(f"/proc/{pid}/stat", encoding="ascii") as stat_file:
        start_ticks = int(stat_file.read().rsplit(")", 1)[1].split()[19])
    with open("/proc/uptime", encoding="ascii") as uptime_file:
        uptime = float(uptime_file.read().split()[0])
    return uptime - start_ticks / os.sysconf("SC_CLK_TCK")


def agentd_age(run_dir):
    for pid_file in glob.glob(os.path.join(run_dir, "wazuh-agentd-*.pid")):
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
    return datetime.fromisoformat(timestamp.strip()[:26].rstrip("Z") + "+00:00").timestamp()


def manager_problems(container, threshold):
    inspect = run(["container", "inspect", "-f", "{{.State.Running}} {{.State.StartedAt}} {{.State.FinishedAt}}", container])
    since_change = None
    if inspect:
        running, started, finished = inspect.split()
        since_change = time.time() - epoch(started if running == "true" else finished)
    listing = run(["container", "exec", container, "/var/ossec/bin/agent_control", "-l"])
    keepalives = {}
    for agent_id, _name, status in parse_agents(listing or ""):
        if agent_id == "000" or status in ACTIVE_AGENT_STATES:
            continue
        detail = run(["container", "exec", container, "/var/ossec/bin/agent_control", "-i", agent_id]) or ""
        match = KEEPALIVE_LINE.search(detail)
        keepalives[agent_id] = int(match.group(1)) if match else None
    return evaluate_manager(listing, keepalives, since_change, time.time(), threshold)


def main():
    parser = argparse.ArgumentParser(description="Check the Wazuh agent on this host and, on the manager host, every registered agent.")
    parser.add_argument("--service", required=True, help="systemd unit of the agent")
    parser.add_argument("--run-dir", required=True, help="the agent's var/run directory")
    parser.add_argument("--threshold", required=True, type=int, help="seconds of tolerated disconnect and of grace after a start")
    parser.add_argument("--manager", help="manager container name; checks every registered agent when set")
    args = parser.parse_args()

    state_path = os.path.join(args.run_dir, "wazuh-agentd.state")
    try:
        with open(state_path, encoding="utf-8") as state_file:
            state = parse_state(state_file.read())
    except FileNotFoundError:
        state = None
    service_active = subprocess.run(["systemctl", "is-active", "--quiet", args.service], check=False).returncode == 0
    problems = evaluate_host(service_active, agentd_age(args.run_dir), state, datetime.now(), args.threshold)
    if args.manager:
        problems += manager_problems(args.manager, args.threshold)

    for problem in problems:
        print(f"❌ {problem}")
    if problems:
        sys.exit(1)
    print(f"✅ No Wazuh agent problem beyond the {args.threshold} s threshold")


if __name__ == "__main__":
    main()
