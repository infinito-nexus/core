#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Gh = Callable[[Sequence[str], bytes | None], bytes]
    Ask = Callable[[str], str]
    Say = Callable[[str], None]

GH_TIMEOUT_SECONDS = 120
INSTALLATION_TOKEN_SECONDS = 3600
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
                '.branch_policies[] | "\\(.type):\\(.name)"',
            ],
            None,
        )
    )
    if policies != [f"branch:{UPDATER_BRANCH}"]:
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
        SystemExit: the file is missing or holds no unencrypted RSA private key.
    """
    if not path.is_file():
        raise SystemExit(f"no file at {path}")
    data = path.read_bytes()  # nocheck: cache-read
    try:
        key = load_pem_private_key(data, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise SystemExit(f"{path} holds no unencrypted PEM private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SystemExit(f"{path} holds no RSA private key")
    return data


def ask_client_id(ask: Ask, say: Say, app: str) -> str:
    say(
        f"   In the left menu of {app} open 'General'; under 'About' copy the 'Client ID'."
    )
    value = ask("   Client ID (starts with Iv): ").strip()
    if not _CLIENT_ID.fullmatch(value):
        raise SystemExit(f"{value!r} is no GitHub App Client ID; it starts with Iv")
    return value


def confirm(ask: Ask, question: str) -> None:
    if ask(f"{question} [y/N] ").strip().lower() != "y":
        raise SystemExit("stopped; run again once that step is done")


def wait(ask: Ask, what: str) -> None:
    ask(f"   {what} Press Enter when done.")


def newest_pem(downloads: Path, since: float) -> Path | None:
    """
    Args:
        downloads: the directory the browser saves into.
        since: epoch seconds; older files are ignored.

    Returns:
        the most recently modified ``*.pem`` saved at or after *since*, or
        ``None`` when there is none.
    """
    fresh = [p for p in downloads.glob("*.pem") if p.stat().st_mtime >= since]
    return max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None


def ask_pem(ask: Ask, say: Say, downloads: Path | None, since: float) -> Path:
    found = newest_pem(downloads, since) if downloads is not None else None
    if found is None:
        return Path(ask("   Path of the downloaded .pem: ").strip()).expanduser()
    say(f"   Found the new key {found}")
    typed = ask("   Press Enter to use it, or type another path: ").strip()
    return Path(typed).expanduser() if typed else found


def generate_key(ask: Ask, say: Say, page: str) -> float:
    since = time.time()
    say(f"   Open {page}")
    say(
        "   In the left menu open 'Credentials', tab 'Key pairs', press 'Generate a private key'."
    )
    wait(ask, "The browser downloads a .pem file.")
    return since


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


def rotate_updater_key(
    gh: Gh, repo: str, slug: str, downloads: Path | None, ask: Ask, say: Say
) -> Path:
    org = repo.split("/", maxsplit=1)[0]
    say(f"\nStep 1 of 4: new key for the updater App {slug}")
    since = generate_key(ask, say, app_page(org, slug))
    pem = ask_pem(ask, say, downloads, since)
    key = read_private_key(pem)
    client_id = ask_client_id(ask, say, slug)
    set_secret(gh, repo, UPDATER_NAMES[0], client_id.encode(), UPDATER_ENVIRONMENT)
    set_secret(gh, repo, UPDATER_NAMES[1], key, UPDATER_ENVIRONMENT)
    say(f"   stored {', '.join(UPDATER_NAMES)} in environment {UPDATER_ENVIRONMENT}")
    say("   Back in 'Credentials', tab 'Key pairs': delete every key except the newest")
    say("   one (the one created just now, see its date).")
    confirm(ask, "   Only the new updater key is left?")
    ready = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(time.time() + INSTALLATION_TOKEN_SECONDS)
    )
    say("   Tokens minted with the old keys stay valid up to one hour: delete the")
    say(f"   pre-rotation update/** and dependabot/** branches after {ready}.")
    return pem


def create_translate_app(
    gh: Gh, repo: str, slug: str, downloads: Path | None, ask: Ask, say: Say
) -> Path:
    org = repo.split("/", maxsplit=1)[0]
    say(f"\nStep 2 of 4: create the translation App {slug}")
    say(f"   Open {new_app_url(org, repo, slug)}")
    say(
        "   The form is prefilled: no webhook, Contents and Pull requests read and write."
    )
    wait(ask, "Scroll down and press 'Create GitHub App'.")
    since = generate_key(ask, say, app_page(org, slug))
    pem = ask_pem(ask, say, downloads, since)
    key = read_private_key(pem)
    client_id = ask_client_id(ask, say, slug)
    say(
        "   In the left menu open 'Install App', press 'Install' next to the organization,"
    )
    say(
        f"   choose 'Only select repositories', pick {repo.split('/', maxsplit=1)[1]}, press 'Install'."
    )
    confirm(ask, f"   {slug} is installed on {repo} alone?")
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
    parser.add_argument(
        "--downloads",
        type=Path,
        help="Directory the browser saves into; the newest .pem there is offered",
    )
    args = parser.parse_args(argv)

    gh(["auth", "status"], None)
    ensure_environment(gh, args.repo, say)
    pems = []
    if not args.skip_updater:
        pems.append(
            rotate_updater_key(
                gh, args.repo, args.updater_slug, args.downloads, ask, say
            )
        )
    pems.append(
        create_translate_app(
            gh, args.repo, args.translate_slug, args.downloads, ask, say
        )
    )
    say("\nStep 3 of 4: repository copies of the updater key")
    drop_repository_copies(gh, args.repo, say)
    say("\nStep 4 of 4: downloaded keys")
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
