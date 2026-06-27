from __future__ import annotations

import json
import re
import subprocess

_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run>\d+)"
)


def gh_proc(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` with the given arguments and return the completed process."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def gh(args: list[str]) -> str:
    """Run ``gh`` and return stdout, raising on a non-zero exit."""
    proc = gh_proc(args)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, proc.stdout, proc.stderr
        )
    return proc.stdout


def resolve_run(ref: str, repo_override: str | None) -> tuple[str, str, str]:
    """Return (owner, repo, run_id) from a run id or a run/job URL.

    A bare run id resolves owner/repo from ``repo_override`` or the current gh repo.
    """
    m = _URL_RE.search(ref)
    if m:
        return m.group("owner"), m.group("repo"), m.group("run")
    if not ref.isdigit():
        raise ValueError(f"not a run id or a run URL: {ref!r}")
    nwo = (
        repo_override
        or gh(
            ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
        ).strip()
    )
    owner, _, repo = nwo.partition("/")
    if not repo:
        raise ValueError(
            f"could not resolve OWNER/REPO (got {nwo!r}); pass --repo OWNER/REPO"
        )
    return owner, repo, ref


def list_jobs(owner: str, repo: str, run: str) -> list[dict]:
    out = gh(
        [
            "api",
            f"repos/{owner}/{repo}/actions/runs/{run}/jobs",
            "--paginate",
            "--jq",
            ".jobs[] | {id, name, conclusion, status}",
        ]
    )
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def list_artifacts(owner: str, repo: str, run: str) -> list[str]:
    out = gh(
        [
            "api",
            f"repos/{owner}/{repo}/actions/runs/{run}/artifacts",
            "--paginate",
            "--jq",
            ".artifacts[].name",
        ]
    )
    return [line.strip() for line in out.splitlines() if line.strip()]
