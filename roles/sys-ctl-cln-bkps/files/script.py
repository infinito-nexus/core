import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil

# Validating arguments
parser = argparse.ArgumentParser()
parser.add_argument(
    "--maximum-backup-size-percent",
    type=int,
    dest="maximum_backup_size_percent",
    required=True,
    choices=range(100),
    help="The directory from which the data should be encrypted.",
)
parser.add_argument(
    "--backups-folder-path",
    type=str,
    dest="backup_dir",
    required=True,
    help="The folder in which the backups are stored",
)
args = parser.parse_args()


def print_used_disc_space(backup_dir):
    print(
        f"{psutil.disk_usage(backup_dir).percent:.0f} % of disk {backup_dir} are used"
    )


def is_directory_used_by_another_process(directory_path):
    command = "lsof " + directory_path
    # directory_path comes from Ansible-templated config (host-trusted), not user input.
    process = subprocess.Popen(  # noqa: S602
        [command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )
    process.communicate()
    # @See https://stackoverflow.com/questions/29841984/non-zero-exit-code-for-lsof
    return not process.wait() > bool(0)


def is_larger_than_maximum_backup_size(maximum_backup_size_percent, backup_dir):
    current_disc_usage_percent = psutil.disk_usage(backup_dir).percent
    return current_disc_usage_percent > maximum_backup_size_percent


def is_directory_deletable(version, versions, version_path):
    print(f"Checking directory {version_path} ...")
    if version == versions[-1]:
        print(
            f"Directory {version_path} contains the last version of the backup. Skipped."
        )
        return False

    if is_directory_used_by_another_process(version_path):
        print(f"Directory {version_path} is used by another process. Skipped.")
        return False

    print(f"Directory {version_path} can be deleted.")
    return True


def delete_version(version_path, backup_dir):
    print(f"Deleting {version_path} to free space.")
    current_disc_usage_percent = psutil.disk_usage(backup_dir).percent
    shutil.rmtree(version_path)
    new_disc_usage_percent = psutil.disk_usage(backup_dir).percent
    difference_percent = current_disc_usage_percent - new_disc_usage_percent
    print(f"{difference_percent:6.2f} %% of drive freed")


def count_total_application_directories(backup_dir):
    total_app_directories = 0
    for host_backup_directory_name in os.listdir(backup_dir):
        host_backup_directory_path = str(Path(backup_dir) / host_backup_directory_name)
        total_app_directories += sum(
            Path(str(Path(host_backup_directory_path) / d)).is_dir()
            for d in os.listdir(host_backup_directory_path)
        )
    return total_app_directories


def count_total_version_folders(backup_dir):
    total_version_folders = 0
    for host_backup_directory_name in os.listdir(backup_dir):
        host_backup_directory_path = str(Path(backup_dir) / host_backup_directory_name)
        for application_directory in os.listdir(host_backup_directory_path):
            versions_directory = str(
                Path(host_backup_directory_path) / application_directory
            )
            total_version_folders += sum(
                Path(str(Path(versions_directory) / d)).is_dir()
                for d in os.listdir(versions_directory)
            )
    return total_version_folders


def average_version_directories_per_application(backup_dir):
    total_app_directories = count_total_application_directories(backup_dir)
    total_version_folders = count_total_version_folders(backup_dir)

    if total_app_directories == 0:
        return 0

    average = total_version_folders / total_app_directories
    return int(average)


def get_amount_of_iteration(versions, average_version_directories_per_application):
    version_amount = len(versions)
    amount_of_iterations = (
        len(versions) + 1
    ) - average_version_directories_per_application
    print(f"Number of existing versions: {version_amount}")
    print(
        f"Number of average version directories per application: {average_version_directories_per_application}"
    )
    print(f"Amount of iterations: {amount_of_iterations}")
    return amount_of_iterations


def delete_iteration(backup_dir, average_version_directories_per_application):
    for host_backup_directory_name in os.listdir(backup_dir):
        print(f"Iterating over host: {host_backup_directory_name}")
        host_backup_directory_path = str(Path(backup_dir) / host_backup_directory_name)
        for application_directory in os.listdir(host_backup_directory_path):
            print(f"Iterating over backup application: {application_directory}")
            # The directory which contains all backup versions of the application
            versions_directory = (
                str(Path(host_backup_directory_path) / application_directory) + "/"
            )

            versions = os.listdir(versions_directory)
            versions.sort(reverse=False)
            version_iteration = 0
            while version_iteration < get_amount_of_iteration(
                versions, average_version_directories_per_application
            ):
                print_used_disc_space(backup_dir)
                version = versions[version_iteration]
                version_path = str(Path(versions_directory) / version)
                if is_directory_deletable(version, versions, version_path):
                    delete_version(version_path, backup_dir)
                version_iteration += 1


def check_time_left(start_time, time_limit):
    """
    Checks if there is time left within the given time limit.
    Prints the start time, the current time, and the remaining time.

    :param start_time: The start time of the process.
    :param time_limit: The total time limit for the process.
    :return: True if there is time left, False otherwise.
    """
    current_time = time.time()
    elapsed_time = current_time - start_time
    remaining_time = time_limit - elapsed_time

    # Convert times to readable format
    start_time_str = time.strftime("%H:%M:%S", time.localtime(start_time))
    current_time_str = time.strftime("%H:%M:%S", time.localtime(current_time))
    remaining_time_str = time.strftime("%H:%M:%S", time.gmtime(remaining_time))
    is_time_left = remaining_time > 0

    print(f"Start time: {start_time_str}")
    print(f"Current time: {current_time_str}")
    if is_time_left:
        print(f"Remaining time: {remaining_time_str}")

    return remaining_time > 0


class TimeLimitExceededError(Exception):
    """Exception raised when the time limit for the process is exceeded."""

    def __init__(self, message="Time limit exceeded, terminating the process."):
        self.message = message
        super().__init__(self.message)


backup_dir = args.backup_dir
maximum_backup_size_percent = args.maximum_backup_size_percent
start_time = time.time()
time_limit = 3600
itteration_counter = 1
while is_larger_than_maximum_backup_size(maximum_backup_size_percent, backup_dir):
    print(f"Delete Iteration: {itteration_counter}")
    if not check_time_left(start_time, time_limit):
        raise TimeLimitExceededError

    average_version_directories = average_version_directories_per_application(
        backup_dir
    )
    if average_version_directories <= 0:
        print(
            "No backup versions found to delete (average_version_directories=0). Exiting."
        )
        break
    print(
        f"Average version directories per application directory: {average_version_directories}"
    )
    delete_iteration(backup_dir, average_version_directories)
    itteration_counter += 1

print_used_disc_space(backup_dir)
print("Cleaning up finished.")
