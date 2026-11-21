"""Read what the merge gate judges from the GitHub REST API through ``gh``."""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Gh = Callable[[Sequence[str]], bytes]

GH_TIMEOUT_SECONDS = 120
ROLE_RUNTIMES_PREFIX = "role-runtimes-"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_CSV_BYTES = 4 * 1024 * 1024


def run_gh(args: Sequence[str]) -> bytes:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        check=True,
        timeout=GH_TIMEOUT_SECONDS,
    ).stdout


def items(gh: Gh, path: str, jq: str) -> list[dict[str, Any]]:
    """Every object a paginated REST list yields through *jq*.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        path: the REST path, query string included.
        jq: a filter emitting one JSON object per item.

    Returns:
        the objects, across all pages.
    """
    out = gh(["api", "--paginate", path, "--jq", jq]).decode("utf-8")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def open_pull_requests(gh: Gh, repo: str, sha: str) -> list[dict[str, Any]]:
    """The open pull requests whose head commit is *sha*."""
    return [
        pr
        for pr in items(gh, f"repos/{repo}/commits/{sha}/pulls?per_page=100", ".[]")
        if pr["state"] == "open" and pr["head"]["sha"] == sha
    ]


def check_runs(gh: Gh, repo: str, sha: str) -> list[dict[str, Any]]:
    """The latest check run per name on *sha*."""
    return items(
        gh,
        f"repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100",
        ".check_runs[] | {name, status, conclusion, details_url}",
    )


def statuses(gh: Gh, repo: str, sha: str) -> list[dict[str, Any]]:
    """The latest commit status per context on *sha*."""
    return items(
        gh,
        f"repos/{repo}/commits/{sha}/status?per_page=100",
        ".statuses[] | {context, state}",
    )


def changed_paths(gh: Gh, repo: str, number: int) -> list[str]:
    """Every path pull request *number* touches, old names of renamed files included."""
    paths: list[str] = []
    for entry in items(
        gh,
        f"repos/{repo}/pulls/{number}/files?per_page=100",
        ".[] | {filename, previous_filename}",
    ):
        paths.append(entry["filename"])
        if entry["previous_filename"]:
            paths.append(entry["previous_filename"])
    return paths


def csv_members(blob: bytes) -> list[str]:
    """The CSV files inside an artifact zip, read in memory.

    The zip is never extracted to disk, so its member names cannot reach a
    path, and a member larger than ``MAX_CSV_BYTES`` is left out.

    Args:
        blob: the artifact zip as the REST API serves it.

    Returns:
        the text of each ``*.csv`` member.
    """
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.endswith(".csv"):
                continue
            if member.file_size > MAX_CSV_BYTES:
                continue
            with archive.open(member) as handle:
                data = handle.read(MAX_CSV_BYTES + 1)
            if len(data) <= MAX_CSV_BYTES:
                texts.append(data.decode("utf-8", errors="replace"))
    return texts


def role_runtime_csvs(gh: Gh, repo: str, run_id: int) -> list[str]:
    """The ``role-runtimes-*`` CSVs workflow run *run_id* uploaded.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        repo: ``owner/name``.
        run_id: the pull request run whose deploy rows uploaded them.

    Returns:
        the text of every CSV in every unexpired ``role-runtimes-*`` artifact
        of at most ``MAX_ARTIFACT_BYTES``.
    """
    texts: list[str] = []
    for artifact in items(
        gh,
        f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
        ".artifacts[] | {id, name, expired, size_in_bytes}",
    ):
        if not artifact["name"].startswith(ROLE_RUNTIMES_PREFIX):
            continue
        if artifact["expired"] or artifact["size_in_bytes"] > MAX_ARTIFACT_BYTES:
            continue
        blob = gh(["api", f"repos/{repo}/actions/artifacts/{artifact['id']}/zip"])
        texts.extend(csv_members(blob))
    return texts
