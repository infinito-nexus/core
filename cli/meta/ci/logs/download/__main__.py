from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

from .fetch import download_artifact, download_log, write_manifest
from .github import list_artifacts, list_jobs, resolve_run

_FLAG_TO_CONCLUSION = {
    "success": "success",
    "failed": "failure",
    "cancelled": "cancelled",
    "skipped": "skipped",
}


def _selected_conclusions(args: argparse.Namespace) -> set[str] | None:
    picked = {
        conclusion
        for flag, conclusion in _FLAG_TO_CONCLUSION.items()
        if getattr(args, flag)
    }
    return picked or None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.ci.logs.download",
        description=(
            "Download GitHub Actions job logs and run artifacts for a CI run. "
            "RUN is a run id or a run/job URL. Conclusion flags filter which "
            "jobs' logs are fetched; none given fetches every completed job."
        ),
    )
    p.add_argument("run", help="Run id (e.g. 28223007623) or a run/job URL.")
    p.add_argument(
        "-s", "--success", action="store_true", help="Include succeeded jobs."
    )
    p.add_argument("-f", "--failed", action="store_true", help="Include failed jobs.")
    p.add_argument(
        "-c", "--cancelled", action="store_true", help="Include cancelled jobs."
    )
    p.add_argument("-k", "--skipped", action="store_true", help="Include skipped jobs.")
    p.add_argument(
        "-d", "--destination", help="Target directory (default: /tmp/logs/<run-id>)."
    )
    p.add_argument("-R", "--repo", help="OWNER/REPO override for a bare run id.")
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="Parallel download workers (default: CPU count).",
    )
    p.add_argument("--no-logs", action="store_true", help="Skip job logs.")
    p.add_argument("--no-artifacts", action="store_true", help="Skip run artifacts.")
    return p


def _download_logs(owner, repo, run, jobs, args, dest, workers, delay_max):
    want = _selected_conclusions(args)
    # In-progress jobs (conclusion=null) have no log endpoint yet; skip them.
    sel = [
        j
        for j in jobs
        if j.get("status") == "completed"
        and (want is None or j.get("conclusion") in want)
    ]
    logdir = dest / "logs"
    logdir.mkdir(exist_ok=True)
    scope = "all" if want is None else ",".join(sorted(want))
    total = len(sel)
    print(f"[ci-logs] {total}/{len(jobs)} jobs match [{scope}]; downloading logs...")
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download_log, owner, repo, j, logdir, delay_max) for j in sel
        ]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            name, success = fut.result()
            ok += success
            short = name.split("/")[-1].strip()
            print(
                f"[ci-logs]   [{i}/{total}] {'✓' if success else '✗'} {short}",
                flush=True,
            )
    print(f"[ci-logs] logs: {ok}/{total} -> {logdir}")


def _download_artifacts(owner, repo, run, dest, workers, delay_max):
    artdir = dest / "artifacts"
    artdir.mkdir(exist_ok=True)
    try:
        names = list_artifacts(owner, repo, run)
    except subprocess.CalledProcessError as exc:
        print(
            f"[ci-logs] could not list artifacts: {(exc.stderr or '').strip()}",
            file=sys.stderr,
        )
        return
    if not names:
        print("[ci-logs] artifacts: none")
        return
    total = len(names)
    print(f"[ci-logs] {total} artifacts; downloading...")
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download_artifact, owner, repo, run, n, artdir, delay_max)
            for n in names
        ]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            name, success = fut.result()
            ok += success
            print(
                f"[ci-logs]   [{i}/{total}] {'✓' if success else '✗'} {name}",
                flush=True,
            )
    files = sum(1 for f in artdir.rglob("*") if f.is_file())
    print(f"[ci-logs] artifacts: {ok}/{total} ({files} files) -> {artdir}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        owner, repo, run = resolve_run(args.run, args.repo)
    except ValueError as exc:
        print(f"[ci-logs] {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"[ci-logs] gh failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 1

    dest = Path(args.destination) if args.destination else Path("/tmp/logs") / run  # noqa: S108 - default CI log dir, overridable via --destination
    dest.mkdir(parents=True, exist_ok=True)
    workers = max(1, args.jobs)
    delay_max = workers * 2
    print(
        f"[ci-logs] {owner}/{repo} run {run} -> {dest} ({workers} workers, 1-{delay_max}s jitter)"
    )

    try:
        jobs = list_jobs(owner, repo, run)
    except subprocess.CalledProcessError as exc:
        print(
            f"[ci-logs] could not list jobs: {(exc.stderr or '').strip()}",
            file=sys.stderr,
        )
        jobs = []
    if jobs:
        write_manifest(jobs, dest)
        print(f"[ci-logs] manifest: {len(jobs)} jobs -> jobs.json, summary.tsv")

    if not args.no_logs and jobs:
        _download_logs(owner, repo, run, jobs, args, dest, workers, delay_max)
    if not args.no_artifacts:
        _download_artifacts(owner, repo, run, dest, workers, delay_max)

    print(f"[ci-logs] done: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
