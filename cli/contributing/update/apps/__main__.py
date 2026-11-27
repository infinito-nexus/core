#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Gh = Callable[[Sequence[str], bytes | None], bytes]
    Ask = Callable[[str], str]
    Say = Callable[[str], None]

GH_TIMEOUT_SECONDS = 120
UPDATER_ENVIRONMENT = "updater"
UPDATER_BRANCH = "main"
UPDATER_NAMES = ("BOT_APP_CLIENT_ID", "BOT_APP_PRIVATE_KEY")
TRANSLATE_NAMES = ("TRANSLATE_APP_CLIENT_ID", "TRANSLATE_APP_PRIVATE_KEY")
_CLIENT_ID = re.compile(r"Iv[0-9A-Za-z.]{8,}")


def run_gh(args: Sequence[str], stdin: bytes | None) -> bytes:
    return subprocess.run(
        ["gh", *args],
        input=stdin,
        capture_output=True,
        check=True,
        timeout=GH_TIMEOUT_SECONDS,
    ).stdout


def lines(out: bytes) -> list[str]:
    return [line for line in out.decode("utf-8").splitlines() if line.strip()]


def ensure_environment(gh: Gh, repo: str, say: Say) -> None:
    """
    Args:
        gh: runs ``gh`` with the given arguments and stdin, returns its stdout.
        repo: ``owner/name``.
        say: prints one line to the operator.

    Raises:
        SystemExit: the environment exists with other deployment branches.
    """
    path = f"repos/{repo}/environments/{UPDATER_ENVIRONMENT}"
    names = lines(
        gh(["api", f"repos/{repo}/environments", "--jq", ".environments[].name"], None)
    )
    if UPDATER_ENVIRONMENT not in names:
        gh(
            [
                "api",
                "--method",
                "PUT",
                path,
                "-F",
                "deployment_branch_policy[protected_branches]=false",
                "-F",
                "deployment_branch_policy[custom_branch_policies]=true",
            ],
            None,
        )
        gh(
            [
                "api",
                "--method",
                "POST",
                f"{path}/deployment-branch-policies",
                "-f",
                f"name={UPDATER_BRANCH}",
                "-f",
                "type=branch",
            ],
            None,
        )
        say(
            f"created environment {UPDATER_ENVIRONMENT}, restricted to {UPDATER_BRANCH}"
        )
        return
    policies = lines(
        gh(
            [
                "api",
                f"{path}/deployment-branch-policies",
                "--jq",
                ".branch_policies[].name",
            ],
            None,
        )
    )
    if policies != [UPDATER_BRANCH]:
        raise SystemExit(
            f"environment {UPDATER_ENVIRONMENT} allows {policies or 'every branch'}, "
            f"not only {UPDATER_BRANCH}: fix it under https://github.com/{repo}/settings/environments"
        )
    say(f"environment {UPDATER_ENVIRONMENT} exists, restricted to {UPDATER_BRANCH}")


def read_private_key(path: Path) -> bytes:
    """
    Args:
        path: the file the App's settings page downloaded.

    Returns:
        the file's bytes, never printed.

    Raises:
        SystemExit: the file is missing or holds no PEM private key.
    """
    if not path.is_file():
        raise SystemExit(f"no file at {path}")
    data = path.read_bytes()  # nocheck: cache-read
    if b"-----BEGIN" not in data or b"PRIVATE KEY-----" not in data:
        raise SystemExit(f"{path} holds no PEM private key")
    return data


def ask_client_id(ask: Ask, app: str) -> str:
    value = ask(f"Client ID of {app} (Iv..., on the App's General page): ").strip()
    if not _CLIENT_ID.fullmatch(value):
        raise SystemExit(f"{value!r} is no GitHub App Client ID; it starts with Iv")
    return value


def confirm(ask: Ask, question: str) -> None:
    if ask(f"{question} [y/N] ").strip().lower() != "y":
        raise SystemExit("stopped; run again once that step is done")


def set_secret(
    gh: Gh, repo: str, name: str, value: bytes, environment: str | None
) -> None:
    """
    Args:
        gh: runs ``gh`` with the given arguments and stdin.
        repo: ``owner/name``.
        name: the secret's name.
        value: the secret's bytes.
        environment: the environment holding it, ``None`` for a repository secret.
    """
    scope = ["--env", environment] if environment is not None else []
    gh(["secret", "set", name, "--repo", repo, *scope], value)


def app_page(org: str, slug: str) -> str:
    return f"https://github.com/organizations/{org}/settings/apps/{slug}"


def new_app_url(org: str, repo: str, name: str) -> str:
    query = urlencode(
        {
            "name": name,
            "url": f"https://github.com/{repo}",
            "public": "false",
            "webhook_active": "false",
            "contents": "write",
            "pull_requests": "write",
        }
    )
    return f"https://github.com/organizations/{org}/settings/apps/new?{query}"


def rotate_updater_key(gh: Gh, repo: str, slug: str, ask: Ask, say: Say) -> Path:
    org = repo.split("/", maxsplit=1)[0]
    say(f"\n1. Updater App: open {app_page(org, slug)}")
    say(
        "   Under 'Private keys' press 'Generate a private key'; the browser downloads a .pem."
    )
    client_id = ask_client_id(ask, slug)
    pem = Path(ask("Path of the downloaded .pem: ").strip()).expanduser()
    key = read_private_key(pem)
    set_secret(gh, repo, UPDATER_NAMES[0], client_id.encode(), UPDATER_ENVIRONMENT)
    set_secret(gh, repo, UPDATER_NAMES[1], key, UPDATER_ENVIRONMENT)
    say(f"   stored {', '.join(UPDATER_NAMES)} in environment {UPDATER_ENVIRONMENT}")
    say(
        f"   Now delete every OLDER key on {app_page(org, slug)}; keep only the one just made."
    )
    confirm(ask, "   Only the new updater key is left?")
    return pem


def create_translate_app(gh: Gh, repo: str, slug: str, ask: Ask, say: Say) -> Path:
    org = repo.split("/", maxsplit=1)[0]
    say(f"\n2. Translation App: open {new_app_url(org, repo, slug)}")
    say(
        "   The form is prefilled (no webhook, Contents and Pull requests write); press 'Create GitHub App'."
    )
    say("   Then 'Generate a private key', and install it on the core repository only:")
    say(f"   https://github.com/apps/{slug}/installations/new")
    confirm(ask, f"   {slug} is created and installed on {repo} alone?")
    client_id = ask_client_id(ask, slug)
    pem = Path(ask("Path of the downloaded .pem: ").strip()).expanduser()
    key = read_private_key(pem)
    set_secret(gh, repo, TRANSLATE_NAMES[0], client_id.encode(), None)
    set_secret(gh, repo, TRANSLATE_NAMES[1], key, None)
    say(
        f"   stored {', '.join(TRANSLATE_NAMES)} as repository secrets; never add {slug} to a bypass list"
    )
    return pem


def drop_repository_copies(gh: Gh, repo: str, say: Say) -> None:
    names = lines(
        gh(
            ["secret", "list", "--repo", repo, "--json", "name", "--jq", ".[].name"],
            None,
        )
    )
    for name in UPDATER_NAMES:
        if name in names:
            gh(["secret", "delete", name, "--repo", repo], None)
            say(f"   deleted repository secret {name}; pull_request runs could read it")


def main(argv: Sequence[str] | None, gh: Gh, ask: Ask, say: Say) -> int:
    """
    Args:
        argv: command-line arguments; ``None`` reads ``sys.argv``.
        gh: runs ``gh`` with the given arguments and stdin, returns its stdout.
        ask: reads one answer from the operator.
        say: prints one line to the operator.

    Returns:
        0 once every secret is in place.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Rotate the updater App key into the main-only updater environment and "
            "set up the separate translation App, through gh and the browser."
        )
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--updater-slug", required=True, help="Slug of the updater App")
    parser.add_argument(
        "--translate-slug", required=True, help="Slug for the translation App"
    )
    parser.add_argument(
        "--skip-updater", action="store_true", help="Updater key already rotated"
    )
    args = parser.parse_args(argv)

    gh(["auth", "status"], None)
    ensure_environment(gh, args.repo, say)
    pems = []
    if not args.skip_updater:
        pems.append(rotate_updater_key(gh, args.repo, args.updater_slug, ask, say))
    pems.append(create_translate_app(gh, args.repo, args.translate_slug, ask, say))
    say("\n3. Repository copies of the updater key")
    drop_repository_copies(gh, args.repo, say)
    say("\n4. Downloaded keys")
    for pem in pems:
        if ask(f"   Delete {pem}? [y/N] ").strip().lower() == "y":
            pem.unlink()
            say(f"   deleted {pem}")
    say(
        "\nDone. Merge the pull request that moves the workflows to these secrets next;"
    )
    say(
        "the merge App joins the Main bypass list only after its prerequisites in secrets.md hold."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(None, run_gh, input, print))
