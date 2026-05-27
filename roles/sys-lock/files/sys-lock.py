#!/usr/bin/env python3
import argparse
import subprocess
import time
from datetime import UTC, datetime

# Global variable definition
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


def check_service_active(service_name):
    """
    Check if a systemd service is currently active or activating.
    """
    result = subprocess.run(
        ["systemctl", "is-active", service_name], stdout=subprocess.PIPE, check=False
    )
    service_status = result.stdout.decode("utf-8").strip()
    is_active = service_status in ["active", "activating"]
    print(f"Service {service_name} is {'active' if is_active else 'not active'}.")
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


def main(services, ignored_services, timeout_sec):
    """
    Main function to process the command-line arguments and perform actions.
    """
    filtered_services = filter_services(services, ignored_services)
    print(f"Services to handle: {services}")
    print(f"Services to ignore: {ignored_services}")
    print(f"Services filtered: {filtered_services}")

    print("Waiting for services to stop.")

    attempt = 0
    max_attempts = get_max_attempts(timeout_sec)
    while check_any_service_active(filtered_services):
        attempt = wait_for_all_services_to_stop(
            filtered_services, max_attempts, attempt
        )
    print("All required services have stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Blocks the code execution as long as defined services are running. Terminates with 0 when all services stopped"
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
    args = parser.parse_args()
    services = args.services
    ignored_services = args.ignore or []
    timeout_seconds = parse_time_to_seconds(args.timeout)
    main(services, ignored_services, timeout_seconds)
