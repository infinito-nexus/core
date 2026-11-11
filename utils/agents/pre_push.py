"""Pre-push guard of an agent workspace.

Git runs it as the ``pre-push`` hook, ``python -m utils.agents.pre_push
--role <firewall role> -- <remote> <url>``, with one
``<local ref> <local sha> <remote ref> <remote sha>`` line per pushed ref on
stdin. It refuses the push unless the agent firewall allows
``app(<remote>/push):create``, and refuses an outgoing diff that holds a value
the home-sync redactor masks. A non-zero exit makes git abort the push before
anything reaches the remote. The remote name is the firewall target, so a
workspace names its remotes ``fork`` and ``upstream``; a push to a bare URL
matches no rule and is denied.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from utils import PROJECT_ROOT
from utils.agents.redact import redact
from utils.cache.yaml import load_yaml
from utils.firewall.compile import VERDICTS, Resolved, decide, resolve

FIREWALL_ROLES = PROJECT_ROOT / "agents" / "firewall" / "roles.yml"
ALLOW = "allow"


def bound(roles: dict, names: list[str]) -> Resolved:
    """Return the firewall of an agent: its bound roles resolved and folded.

    Args:
        roles: the parsed agents/firewall/roles.yml mapping.
        names: the agent's ``firewall_roles``.
    """
    parts = [resolve(roles, name) for name in names]
    return Resolved(
        **{
            v: tuple(rule for part in parts for rule in part.bucket(v))
            for v in VERDICTS
        }
    )


def push_verdict(firewall: Resolved, remote: str) -> str:
    """Return the firewall verdict on a push to ``remote``.

    Args:
        firewall: the agent's resolved firewall.
        remote: the git remote name the push goes to.
    """
    return decide(firewall, "app", f"{remote}/push", "create")


def _is_null(sha: str) -> bool:
    return set(sha) == {"0"}


def outgoing_patch(remote: str, local_sha: str, remote_sha: str) -> str:
    """Return the patch of every commit a ref update sends to ``remote``.

    Args:
        remote: the git remote name; its remote-tracking refs are excluded.
        local_sha: the commit the remote ref is set to, null for a deletion.
        remote_sha: the commit the remote ref holds now, null for a new ref.
    """
    if _is_null(local_sha):
        return ""
    revs = [local_sha, "--not", f"--remotes={remote}"]
    if not _is_null(remote_sha):
        revs.append(remote_sha)
    return subprocess.run(
        ["git", "log", "-p", "--format=", "--no-color", "--no-ext-diff", *revs],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def secret_hits(patch: str) -> list[str]:
    """Return the added lines of ``patch`` that hold a secret, already masked.

    Args:
        patch: a ``git log -p`` patch.
    """
    added = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    original = set(added.splitlines())
    return [line for line in redact(added).splitlines() if line not in original]


def refusals(firewall: Resolved, remote: str, updates: TextIO) -> list[str]:
    """Return why the push must not go out, empty when it may.

    Args:
        firewall: the agent's resolved firewall.
        remote: the git remote name the push goes to.
        updates: git's pre-push stdin, one ref update per line.
    """
    reasons = []
    verdict = push_verdict(firewall, remote)
    if verdict != ALLOW:
        reasons.append(f"firewall {verdict}: app({remote}/push):create")
    for line in updates:
        if not line.strip():
            continue
        fields = line.rsplit(maxsplit=3)
        if len(fields) != 4:
            reasons.append(f"unreadable ref update: {line.strip()}")
            continue
        try:
            patch = outgoing_patch(remote, fields[1], fields[3])
        except subprocess.CalledProcessError:
            reasons.append(f"{fields[0]}: the outgoing commits cannot be read")
            continue
        reasons += [
            f"{fields[0]}: secret in the diff: {hit}" for hit in secret_hits(patch)
        ]
    return reasons


def main(argv: list[str] | None = None, updates: TextIO = sys.stdin) -> int:
    """Run the guard; return 1 to abort the push, 0 to let it go.

    Args:
        argv: ``--role`` (repeatable), optional ``--roles-file``, the remote
            name and its URL, as git passes them.
        updates: git's pre-push stdin.
    """
    parser = argparse.ArgumentParser(prog="pre-push")
    parser.add_argument("--role", action="append", required=True, dest="roles")
    parser.add_argument("--roles-file", type=Path, default=FIREWALL_ROLES)
    parser.add_argument("remote")
    parser.add_argument("url")
    args = parser.parse_args(argv)
    firewall = bound(load_yaml(args.roles_file), args.roles)
    reasons = refusals(firewall, args.remote, updates)
    for reason in reasons:
        print(f"pre-push refused: {reason}", file=sys.stderr)
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
