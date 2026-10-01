"""The bare git repository holding core, its forks and the deployed snapshot."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

DEPLOYED = "deployed"
DEPLOYED_REF = "refs/deployed"
FORKS_PREFIX = "refs/forks"
SHA = re.compile(r"^[0-9a-f]{7,40}$")
NAME = re.compile(
    r"^(?![-/.])(?!.*\.\.)(?!.*//)(?!.*@\{)[A-Za-z0-9._/+@-]{1,200}(?<![./])$"
)
OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
FULL_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
GITHUB = re.compile(
    r"^https://github\.com/(?P<full_name>[A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?$"
)
PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\0\n]{0,1024}$")
GIT_TIMEOUT_SECONDS = 900
GITHUB_TIMEOUT_SECONDS = 30
FORKS_PER_PAGE = 100
LOCK_POLL_SECONDS = 5
SNAPSHOT_DATE = "2000-01-01T00:00:00+00:00"
REF_FORMAT = "%(refname)%00%(if)%(*objectname)%(then)%(*objectname)%(else)%(objectname)%(end)%00%(creatordate:iso-strict)"
LOG_FORMAT = "%H%x00%P%x00%cI%x00%s%x1e"
TODO_PATTERN = r"\b(TODO|FIXME)\b"
TODO_LIMIT = 5000


class InvalidRequestError(ValueError):
    """A ref or path that is malformed."""


class NotFoundError(LookupError):
    """A ref or path that does not exist."""


class Repository:
    """Bare repository of core, its forks and the deployed snapshot.

    Args:
        git_dir: location of the bare repository.
        source: GitHub URL of core.
        forks: ``auto`` to discover forks, ``off`` for none, or a
            space-separated list of ``owner/name``.
        snapshot: directory holding the deployed working tree.
    """

    def __init__(self, git_dir: Path, source: str, forks: str, snapshot: Path):
        match = GITHUB.match(source)
        if not match:
            raise ValueError(f"not a GitHub repository URL: {source}")
        self.git_dir = git_dir
        self.source = source
        self.root = match["full_name"]
        self.forks_setting = forks
        self.snapshot = snapshot
        self.forks_file = git_dir.parent / "forks.json"
        self._lock_handle = None

    def git(self, *args: str, stdin: bytes | None = None, env=None) -> bytes:
        return subprocess.run(
            ["git", "--git-dir", str(self.git_dir), *args],
            input=stdin,
            check=True,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        ).stdout

    def _probe(self, *args: str) -> bytes | None:
        result = subprocess.run(
            ["git", "--git-dir", str(self.git_dir), *args],
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None

    def initialize(self) -> None:
        if not (self.git_dir / "HEAD").is_file():
            subprocess.run(
                ["git", "init", "--bare", "--quiet", str(self.git_dir)], check=True
            )
        self.import_snapshot()

    def import_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            env = {
                **os.environ,
                "GIT_INDEX_FILE": str(Path(scratch) / "index"),
                "GIT_AUTHOR_NAME": "Infinito.Nexus",
                "GIT_AUTHOR_EMAIL": "api@infinito.nexus",
                "GIT_AUTHOR_DATE": SNAPSHOT_DATE,
                "GIT_COMMITTER_NAME": "Infinito.Nexus",
                "GIT_COMMITTER_EMAIL": "api@infinito.nexus",
                "GIT_COMMITTER_DATE": SNAPSHOT_DATE,
            }
            work_tree = ("--work-tree", str(self.snapshot))
            self.git(*work_tree, "add", "--all", "--force", ".", env=env)
            tree = self.git("write-tree", env=env).decode().strip()
            commit = (
                self.git("commit-tree", tree, "-m", "deployed working tree", env=env)
                .decode()
                .strip()
            )
        self.git("update-ref", DEPLOYED_REF, commit)

    def discover_forks(self) -> dict[str, str]:
        """Return the forks to mirror, keyed by owner.

        Returns:
            ``owner`` mapped to ``owner/name``; the previous forks when the
            GitHub API cannot be reached.
        """
        if self.forks_setting == "off":
            return {}
        if self.forks_setting != "auto":
            names = self.forks_setting.split()
        else:
            names, page = [], 1
            try:
                while True:
                    request = urllib.request.Request(
                        f"https://api.github.com/repos/{self.root}/forks"
                        f"?per_page={FORKS_PER_PAGE}&page={page}",
                        headers={"Accept": "application/vnd.github+json"},
                    )
                    with urllib.request.urlopen(  # noqa: S310 - fixed https URL of the GitHub forks endpoint
                        request, timeout=GITHUB_TIMEOUT_SECONDS
                    ) as response:
                        batch = json.load(response)
                    names += [fork["full_name"] for fork in batch]
                    if len(batch) < FORKS_PER_PAGE:
                        break
                    page += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"fork discovery failed: {exc}", file=sys.stderr)
                return self.known_forks()
        return {
            name.split("/")[0]: name
            for name in names
            if FULL_NAME.match(name) and OWNER.match(name.split("/")[0])
        }

    def fetch(self) -> None:
        self.git(
            "fetch",
            "--prune",
            "--quiet",
            "--no-tags",
            self.source,
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
        )
        forks = self.discover_forks()
        for owner, full_name in forks.items():
            try:
                self.git(
                    "fetch",
                    "--prune",
                    "--quiet",
                    "--no-tags",
                    f"https://github.com/{full_name}.git",
                    f"+refs/heads/*:{FORKS_PREFIX}/{owner}/heads/*",
                    f"+refs/tags/*:{FORKS_PREFIX}/{owner}/tags/*",
                )
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"fetch of {full_name} failed: {exc}", file=sys.stderr)
        for line in (
            self.git("for-each-ref", "--format=%(refname)", FORKS_PREFIX)
            .decode()
            .splitlines()
        ):
            if line.split("/")[2] not in forks:
                self.git("update-ref", "-d", line)
        staging = self.forks_file.with_suffix(".json.tmp")
        staging.write_text(json.dumps(forks), encoding="utf-8")
        staging.replace(self.forks_file)

    def known_forks(self) -> dict[str, str]:
        try:
            return json.loads(self.forks_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def fetched(self) -> bool:
        return bool(self.git("for-each-ref", "--count=1", "refs/heads/").strip())

    def acquire_fetcher(self) -> bool:
        if self._lock_handle is not None:
            return True
        handle = (self.git_dir.parent / "fetcher.lock").open("a+")
        try:
            fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._lock_handle = handle
        return True

    def run_fetcher(self, interval: int) -> None:
        while not self.acquire_fetcher():
            time.sleep(LOCK_POLL_SECONDS)
        while True:
            try:
                self.fetch()
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"fetch of {self.source} failed: {exc}", file=sys.stderr)
            time.sleep(interval)

    def _refs(self, prefix: str) -> list[dict]:
        refs = []
        for line in (
            self.git("for-each-ref", f"--format={REF_FORMAT}", prefix)
            .decode()
            .splitlines()
        ):
            name, sha, date = line.split("\0")
            refs.append({"name": name.removeprefix(prefix), "sha": sha, "date": date})
        return refs

    def repositories(self) -> list[dict]:
        """Return core and every fork with their branches and tags."""
        entries = [
            {
                "repository": self.root,
                "url": self.source,
                "root": True,
                "branches": self._refs("refs/heads/"),
                "tags": self._refs("refs/tags/"),
            }
        ]
        for owner, full_name in sorted(self.known_forks().items()):
            entries.append(
                {
                    "repository": full_name,
                    "url": f"https://github.com/{full_name}",
                    "root": False,
                    "branches": self._refs(f"{FORKS_PREFIX}/{owner}/heads/"),
                    "tags": self._refs(f"{FORKS_PREFIX}/{owner}/tags/"),
                }
            )
        return entries

    def resolve(self, ref: str) -> str:
        """Return the commit SHA a ref points at.

        Args:
            ref: ``deployed``, a commit SHA, a branch or tag of core, or
                ``<owner>:<branch or tag>`` of a fork.
        """
        if ref == DEPLOYED:
            candidates = [DEPLOYED_REF]
        else:
            owner, _, name = ref.rpartition(":")
            if (owner and not OWNER.match(owner)) or not NAME.match(name):
                raise InvalidRequestError(f"invalid ref: {ref}")
            prefix = f"{FORKS_PREFIX}/{owner}/" if owner else "refs/"
            candidates = [] if owner or not SHA.match(name) else [name]
            candidates += [f"{prefix}heads/{name}", f"{prefix}tags/{name}"]
        for candidate in candidates:
            sha = self._probe(
                "rev-parse",
                "--verify",
                "--quiet",
                "--end-of-options",
                f"{candidate}^{{commit}}",
            )
            if sha:
                return sha.decode().strip()
        raise NotFoundError(f"unknown ref: {ref}")

    @staticmethod
    def check_path(path: str) -> str:
        if not PATH.match(path):
            raise InvalidRequestError(f"invalid path: {path}")
        return path.strip("/")

    def paths(self, commit: str, prefix: str) -> list[str]:
        output = self.git("ls-tree", "-r", "-z", "--name-only", commit, "--", prefix)
        return [path for path in output.decode("utf-8", "replace").split("\0") if path]

    def blobs(self, commit: str, paths: list[str]) -> dict[str, bytes]:
        """Return the content of every existing file of ``paths`` at ``commit``.

        Args:
            commit: commit SHA.
            paths: repository-relative file paths.
        """
        specs = [path for path in paths if "\n" not in path]
        if not specs:
            return {}
        output = self.git(
            "cat-file",
            "--batch",
            stdin="".join(f"{commit}:{p}\n" for p in specs).encode(),
        )
        result, position = {}, 0
        for path in specs:
            end = output.index(b"\n", position)
            header = output[position:end].decode("utf-8", "replace")
            position = end + 1
            if header.endswith((" missing", " ambiguous")):
                continue
            kind, size = header.rsplit(" ", 2)[1:]
            content = output[position : position + int(size)]
            position += int(size) + 1
            if kind == "blob":
                result[path] = content
        return result

    def listing(self, commit: str, path: str) -> list[dict]:
        spec = f"{commit}:{path}"
        kind = self._probe("cat-file", "-t", "--end-of-options", spec)
        if kind is None or kind.strip() != b"tree":
            raise NotFoundError(f"no directory {path!r}")
        entries = []
        for line in (
            self.git("ls-tree", "-z", "--long", spec)
            .decode("utf-8", "replace")
            .split("\0")
        ):
            if not line:
                continue
            meta, name = line.split("\t", 1)
            _, kind, _, size = meta.split()
            entries.append(
                {
                    "name": name,
                    "type": "directory" if kind == "tree" else "file",
                    "size": None if size == "-" else int(size),
                }
            )
        return entries

    def blob(self, commit: str, path: str) -> bytes:
        content = self.blobs(commit, [path]).get(path)
        if content is None:
            raise NotFoundError(f"no file {path!r}")
        return content

    def log(
        self, commit: str, since: str | None, until: str | None, limit: int
    ) -> list[dict]:
        args = ["log", f"--format={LOG_FORMAT}", f"--max-count={limit}"]
        args += [f"--since={since}"] if since else []
        args += [f"--until={until}"] if until else []
        output = self.git(*args, commit, "--").decode("utf-8", "replace")
        commits = []
        for raw in output.split("\x1e"):
            record = raw.strip("\n")
            if not record:
                continue
            sha, parents, date, message = record.split("\0")
            commits.append(
                {
                    "sha": sha,
                    "parents": parents.split(),
                    "date": date,
                    "message": message,
                }
            )
        return commits

    def todos(self, commit: str) -> dict:
        result = subprocess.run(
            [
                "git",
                "--git-dir",
                str(self.git_dir),
                "grep",
                "-z",
                "-n",
                "-I",
                "-E",
                "-e",
                TODO_PATTERN,
                commit,
                "--",
            ],
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
        items = []
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            location, number, text = line.split("\0", 2)
            path = location.removeprefix(f"{commit}:")
            kind = re.search(TODO_PATTERN, text).group(1)
            items.append(
                {"path": path, "line": int(number), "kind": kind, "text": text.strip()}
            )
            if len(items) >= TODO_LIMIT:
                break
        return {"items": items, "capped": len(items) >= TODO_LIMIT}
