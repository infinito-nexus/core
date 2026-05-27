#!/usr/bin/env python3

import argparse
import subprocess


def run_ansible_vault(action, filename, password_file):
    cmd = ["ansible-vault", action, filename, "--vault-password-file", password_file]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="Manage Ansible Vault")
    parser.add_argument(
        "action", choices=["edit", "decrypt", "encrypt"], help="Vault action"
    )
    parser.add_argument("filename", help="File to process")
    parser.add_argument(
        "--password-file", required=True, help="Path to the Vault password file"
    )
    args = parser.parse_args()

    run_ansible_vault(args.action, args.filename, args.password_file)


if __name__ == "__main__":
    main()
