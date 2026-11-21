#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
from datetime import UTC, datetime

BREAK_TIME_SECONDS = 5


class AttemptError(Exception):
    """A custom exception for maximum number of attempts."""


def parse_time_to_seconds(time_str):
    """
    Convert a time string (e.g., '1h', '30min', '45s') to seconds.
    """
    units = {"s": 1, "min": 60, "h": 3600}
    if time_str[-3:] in units:
        number, unit = time_str[:-3], time_str[-3:]
    elif time_str[-2:] in units:
        number, unit = time_str[:-2], time_str[-2:]
    elif time_str[-1:] in units:
        number, unit = time_str[:-1], time_str[-1:]
    else:
        raise ValueError("Invalid time unit")
    return int(number) * units[unit]


BUSY_ACTIVE_STATES = {"active", "activating", "deactivating", "reloading"}
IDLE_SUB_STATES = {"start-pre", "exited"}


def check_service_active(service_name):
    """Return whether ``service_name`` holds the lock.

    Args:
        service_name: systemd unit name.

    Returns:
        True when the unit runs, starts, reloads or stops, outside ``start-pre``
        and ``exited``.
    """
    result = subprocess.run(
        ["systemctl", "show", "-p", "ActiveState", "-p", "SubState", service_name],
        stdout=subprocess.PIPE,
        check=False,
    )
    states = dict(
        line.split("=", 1)
        for line in result.stdout.decode("utf-8").splitlines()
        if "=" in line
    )
    active_state = states.get("ActiveState", "").strip()
    sub_state = states.get("SubState", "").strip()
    is_active = active_state in BUSY_ACTIVE_STATES and sub_state not in IDLE_SUB_STATES
    print(
        f"Service {service_name} is {active_state}/{sub_state}: "
        f"{'holds the lock' if is_active else 'does not hold the lock'}."
    )
    return is_active


def check_any_service_active(services):
    """
    Check if any service in a given list is active or activating.
    """
    return any(check_service_active(service) for service in services)


def filter_services(services, ignored_services):
    """
    Filter out services that are in the ignored_services list from services list.
    """
    return [service for service in services if service not in ignored_services]


def wait_for_all_services_to_stop(filtered_services, max_attempts, attempt):
    """
    Wait until all services in the list have stopped, with a maximum number of attempts.
    """
    for service in filtered_services:
        while check_service_active(service):
            attempt += 1
            if attempt > max_attempts:
                raise AttemptError(
                    f"Maximum attempts ({max_attempts}) reached. Exiting."
                )
            print(
                f"{datetime.now(tz=UTC).isoformat()}#{attempt}/{max_attempts}: Waiting for {BREAK_TIME_SECONDS} seconds for {service} to stop..."
            )
            time.sleep(BREAK_TIME_SECONDS)
    return attempt


def get_max_attempts(timeout_sec):
    return timeout_sec // BREAK_TIME_SECONDS


def main(services, ignored_services, timeout_sec, proceed_on_timeout=False):
    """Wait until none of ``services`` outside ``ignored_services`` holds the lock.

    Args:
        services: systemd units to wait for.
        ignored_services: units to leave out, such as the caller itself.
        timeout_sec: longest wait in seconds.
        proceed_on_timeout: on timeout, warn and return instead of raising.

    Raises:
        AttemptError: the timeout ran out and ``proceed_on_timeout`` is false.
    """
    filtered_services = filter_services(services, ignored_services)
    print(f"Services to handle: {services}")
    print(f"Services to ignore: {ignored_services}")
    print(f"Services filtered: {filtered_services}")

    print("Waiting for services to stop.")

    attempt = 0
    max_attempts = get_max_attempts(timeout_sec)
    try:
        while check_any_service_active(filtered_services):
            attempt = wait_for_all_services_to_stop(
                filtered_services, max_attempts, attempt
            )
    except AttemptError:
        if not proceed_on_timeout:
            raise
        print(
            f"WARNING: the lock timed out after {timeout_sec}s; proceeding without it.",
            file=sys.stderr,
        )
        return
    print("All required services have stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Waits while any of the given services runs. Exits 0 once they stopped; on timeout it fails, or warns and exits 0 with --proceed-on-timeout."
    )
    parser.add_argument(
        "services", nargs="+", help="List of services to apply the action to."
    )
    parser.add_argument(
        "--ignore",
        nargs="*",
        help="List of services to ignore in the action.",
        default=[],
    )
    parser.add_argument(
        "--timeout",
        help="Timeout for lock actions (e.g., 1h, 30min, 45s).",
        default="1min",
    )
    parser.add_argument(
        "--proceed-on-timeout",
        action="store_true",
        help="On timeout, warn and exit 0 instead of failing.",
    )
    args = parser.parse_args()
    services = args.services
    ignored_services = args.ignore or []
    timeout_seconds = parse_time_to_seconds(args.timeout)
    main(services, ignored_services, timeout_seconds, args.proceed_on_timeout)
