#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    rc: int
    stdout: str
    stderr: str


# Common transient network / transport errors seen with git+https in CI/docker.
# We retry only when we are reasonably sure the failure is transient.
TRANSIENT_MARKERS = (
    "Connection reset by peer",
    "Recv failure",
    "Could not resolve host",
    "Failed to connect",
    "Operation timed out",
    "The requested URL returned error: 5",  # e.g. 502/503/504 sometimes
    "HTTP/2 stream",
    "TLS",
    "SSL",
)


def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[git-pull] {msg}", file=sys.stderr)


def run(cmd: list[str], cwd: str | None, verbose: bool) -> RunResult:
    log(f"run: {' '.join(cmd)} (cwd={cwd})", verbose)
    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return RunResult(
        p.returncode,
        (p.stdout or "").strip(),
        (p.stderr or "").strip(),
    )


def _is_transient_git_failure(r: RunResult) -> bool:
    hay = (r.stderr or "") + "\n" + (r.stdout or "")
    return any(m in hay for m in TRANSIENT_MARKERS)


def run_checked(
    cmd: list[str],
    cwd: str | None,
    verbose: bool,
    *,
    retries: int = 5,
    backoff_cap_seconds: int = 20,
) -> RunResult:
    """
    Run command and raise on failure.

    For likely transient transport/network issues (common in CI/docker),
    retry with exponential backoff.
    """
    last: RunResult | None = None

    for attempt in range(1, retries + 1):
        r = run(cmd, cwd=cwd, verbose=verbose)
        last = r

        if r.rc == 0:
            return r

        transient = _is_transient_git_failure(r)
        if not transient or attempt == retries:
            raise RuntimeError(
                f"Command failed (rc={r.rc}): {' '.join(cmd)}\n"
                f"cwd: {cwd}\n"
                f"stdout:\n{r.stdout}\n"
                f"stderr:\n{r.stderr}\n"
            )

        sleep_s = min(2 ** (attempt - 1), backoff_cap_seconds)
        log(
            f"transient failure detected, retrying in {sleep_s}s "
            f"(attempt {attempt}/{retries})",
            verbose,
        )
        time.sleep(sleep_s)

    # Should never be reached, but keep type-checkers happy.
    if last is not None:
        raise RuntimeError(
            f"Command failed (rc={last.rc}): {' '.join(cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout:\n{last.stdout}\n"
            f"stderr:\n{last.stderr}\n"
        )
    raise RuntimeError("Command failed: unknown error")


def git(dest: str, verbose: bool, *args: str, retries: int = 5) -> RunResult:
    return run_checked(["git", *args], cwd=dest, verbose=verbose, retries=retries)


def ensure_dir(dest: str, verbose: bool) -> None:
    Path(dest).mkdir(parents=True, exist_ok=True)
    log(f"ensure directory exists: {dest}", verbose)


def is_dir_empty(path: str) -> bool:
    try:
        return len(os.listdir(path)) == 0
    except FileNotFoundError:
        return True


def is_git_repo(dest: str) -> bool:
    return Path(str(Path(dest) / ".git")).is_dir()


def remote_exists(dest: str, remote: str, verbose: bool) -> bool:
    r = run(["git", "remote"], cwd=dest, verbose=verbose)
    # "git remote" should not fail for a valid repo; if it does, treat as fatal.
    if r.rc != 0:
        raise RuntimeError(
            f"Command failed (rc={r.rc}): git remote\n"
            f"cwd: {dest}\n"
            f"stdout:\n{r.stdout}\n"
            f"stderr:\n{r.stderr}\n"
        )
    return remote in r.stdout.splitlines()


def tag_exists(dest: str, tag: str, verbose: bool) -> bool:
    r = run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=dest,
        verbose=verbose,
    )
    return r.rc == 0


def delete_tag_if_exists(dest: str, tag: str, verbose: bool) -> bool:
    if not tag_exists(dest, tag, verbose):
        return False
    log(f"deleting local tag: {tag}", verbose)
    git(dest, verbose, "tag", "-d", tag, retries=3)
    return True


def get_local_tag_commit(dest: str, tag: str, verbose: bool) -> str:
    r = run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=dest,
        verbose=verbose,
    )
    return r.stdout.strip() if r.rc == 0 else ""


def resolve_remote_tag_commit(dest: str, remote: str, tag: str, verbose: bool) -> str:
    # Annotated tags: tag^{} resolves to the tagged commit.
    r = run_checked(
        ["git", "ls-remote", "--tags", remote, f"{tag}^{{}}"],
        cwd=dest,
        verbose=verbose,
        retries=5,
    )
    if r.stdout:
        return r.stdout.split()[0]

    # Lightweight tags
    r = run_checked(
        ["git", "ls-remote", "--tags", remote, tag],
        cwd=dest,
        verbose=verbose,
        retries=5,
    )
    if r.stdout:
        return r.stdout.split()[0]

    return ""


def clone_shallow(
    repo_url: str, dest: str, branch: str, depth: int, verbose: bool
) -> None:
    log(f"cloning repo (shallow): {repo_url} → {dest}", verbose)
    run_checked(
        ["git", "clone", "--depth", str(depth), "--branch", branch, repo_url, dest],
        cwd=None,
        verbose=verbose,
        retries=5,
    )


def fetch_branch_shallow(
    dest: str, remote: str, branch: str, depth: int, verbose: bool
) -> None:
    log(f"updating branch {branch} from {remote} (shallow)", verbose)
    git(dest, verbose, "fetch", "--depth", str(depth), remote, branch, retries=5)
    git(dest, verbose, "checkout", "-B", branch, f"{remote}/{branch}", retries=3)


def fetch_tag_shallow(
    dest: str, remote: str, tag: str, depth: int, verbose: bool
) -> None:
    log(f"fetching tag {tag} (shallow)", verbose)
    git(dest, verbose, "fetch", "--depth", str(depth), remote, "tag", tag, retries=5)


def checkout_detached(dest: str, ref: str, verbose: bool) -> None:
    log(f"checking out detached ref: {ref}", verbose)
    git(dest, verbose, "checkout", "--detach", ref, retries=3)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Shallow git pull with optional tag pin and tag-conflict healing."
    )
    ap.add_argument("--repo-url", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--pin-tag", default="")
    ap.add_argument("--remove-tag", action="append", default=[])
    ap.add_argument("--mark-changed-on-tag-move", action="store_true")
    ap.add_argument("--verbose", action="store_true")

    args = ap.parse_args()
    v = args.verbose

    ensure_dir(args.dest, v)
    log(f"destination: {args.dest}", v)

    changed = False
    moved = False

    if not is_git_repo(args.dest):
        if not is_dir_empty(args.dest):
            raise RuntimeError(
                f"Destination exists, is not a git repo, and is not empty: {args.dest}"
            )
        clone_shallow(args.repo_url, args.dest, args.branch, args.depth, v)
        changed = True
    else:
        if not remote_exists(args.dest, args.remote, v):
            raise RuntimeError(f"Remote '{args.remote}' not configured")

        for t in args.remove_tag:
            if delete_tag_if_exists(args.dest, t, v):
                changed = True

        fetch_branch_shallow(args.dest, args.remote, args.branch, args.depth, v)

    if args.pin_tag:
        local_before = get_local_tag_commit(args.dest, args.pin_tag, v)
        remote_commit = resolve_remote_tag_commit(
            args.dest, args.remote, args.pin_tag, v
        )

        if (
            args.mark_changed_on_tag_move
            and remote_commit
            and local_before
            and local_before != remote_commit
        ):
            moved = True
            log(f"tag moved: {local_before} → {remote_commit}", v)

        fetch_tag_shallow(args.dest, args.remote, args.pin_tag, args.depth, v)
        checkout_detached(args.dest, args.pin_tag, v)

        if not local_before:
            changed = True

    if moved:
        changed = True

    # machine-readable output (stdout!)
    print(f"CHANGED={str(changed).lower()}")
    if args.pin_tag:
        print(f"PIN_TAG={args.pin_tag}")
        print(f"TAG_MOVED={str(moved).lower()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
