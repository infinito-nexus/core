"""
Delete GHCR mirror packages by visibility.

Lists all container packages under the given namespace that match the
prefix and visibility filter, then deletes them via the GitHub Packages API.

Usage:
    python -m cli.contributing.mirror.cleanup \\
        --ghcr-namespace <user|org> \\
        --ghcr-prefix <prefix> \\
        [--visibility private] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def _gh_request(method: str, url: str, token: str) -> dict | list | None:
    # All call sites build URLs from `https://api.github.com/…` literals
    # plus a project-controlled `namespace`/`package` segment, so no
    # arbitrary scheme can slip in.
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        body = resp.read()
        return json.loads(body) if body else None


def _resolve_account_type(namespace: str, token: str) -> str:
    """Return 'orgs' if namespace is a GitHub org, 'users' otherwise."""
    url = f"https://api.github.com/orgs/{namespace}/packages?package_type=container&per_page=1"
    try:
        _gh_request("GET", url, token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(
                f"[cleanup] '{namespace}' is not an org — using user account endpoint.",
                flush=True,
            )
            return "users"
        raise
    return "orgs"


def _list_packages(
    namespace: str, token: str, account_type: str, visibility: str
) -> Iterator[dict]:
    """Yield all container packages matching the visibility filter."""
    if account_type == "orgs":
        base = f"https://api.github.com/orgs/{namespace}/packages"
        vis_params = [f"&visibility={visibility}"]
    else:
        base = "https://api.github.com/user/packages"
        vis_params = [f"&visibility={visibility}"]

    for vis in vis_params:
        page = 1
        while True:
            data = _gh_request(
                "GET",
                f"{base}?package_type=container&per_page=100&page={page}{vis}",
                token,
            )
            if not data:
                break
            yield from data
            if len(data) < 100:
                break
            page += 1


def _delete_package(
    namespace: str, pkg_name: str, token: str, account_type: str
) -> None:
    encoded = urllib.parse.quote(pkg_name, safe="")
    if account_type == "orgs":
        url = f"https://api.github.com/orgs/{namespace}/packages/container/{encoded}"
    else:
        url = f"https://api.github.com/user/packages/container/{encoded}"
    _gh_request("DELETE", url, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete GHCR mirror packages by visibility."
    )
    parser.add_argument(
        "--ghcr-namespace", required=True, help="GitHub org/user namespace"
    )
    parser.add_argument(
        "--ghcr-prefix",
        default="mirror",
        help="Package name prefix filter (default: mirror)",
    )
    parser.add_argument(
        "--visibility",
        default="private",
        choices=["private", "public", "internal"],
        help="Only delete packages with this visibility (default: private)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List packages that would be deleted without deleting them",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("[cleanup] ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1

    namespace = args.ghcr_namespace.lower()
    prefix = args.ghcr_prefix.strip("/")
    visibility = args.visibility
    dry_run = args.dry_run

    print(
        f"[cleanup] Namespace:   {namespace}",
        flush=True,
    )
    print(f"[cleanup] Prefix:      {prefix}/", flush=True)
    print(f"[cleanup] Visibility:  {visibility}", flush=True)
    print(f"[cleanup] Dry-run:     {dry_run}", flush=True)

    account_type = _resolve_account_type(namespace, token)

    deleted = 0
    skipped = 0
    failures: list[str] = []

    for pkg in _list_packages(namespace, token, account_type, visibility):
        name: str = pkg.get("name", "")
        if not name.startswith(f"{prefix}/"):
            continue

        if dry_run:
            print(f"[cleanup] would delete: {name}", flush=True)
            skipped += 1
            continue

        print(f"[cleanup] deleting: {name} …", flush=True)
        try:
            _delete_package(namespace, name, token, account_type)
            print(f"[cleanup] ✓ deleted: {name}", flush=True)
            deleted += 1
        except urllib.error.HTTPError as e:
            print(
                f"[cleanup] ✗ failed to delete '{name}': HTTP {e.code}",
                file=sys.stderr,
                flush=True,
            )
            failures.append(name)

    if dry_run:
        print(f"\n[cleanup] Dry-run complete: {skipped} package(s) would be deleted.")
    else:
        print(
            f"\n[cleanup] Done: {deleted} deleted, {len(failures)} failed.",
            flush=True,
        )

    if failures:
        print("[cleanup] Failed packages:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
