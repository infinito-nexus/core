from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.pin import KEY as PIN_FILE_KEY
from utils.env.handlers.infinito.cache.pin import ROOT_KEY as PIN_ROOT_KEY

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

APPLIED_SUFFIX = ".applied"
DECLARE_HINT = "the declarer runs `make cache-declare ref=<commit>`"
BUMP_HINT = "ask the declarer to bump the pin"
FULL_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
IGNORED_FIELDS = frozenset({"role"})
HOST_DEFAULTS = {"hijack": True}
ARTEFACTS = "artefacts"


class PinError(Exception):
    pass


UNREADABLE = (
    PinError,
    OSError,
    subprocess.CalledProcessError,
    json.JSONDecodeError,
    KeyError,
)


def env_path(key: str, environ: Mapping[str, str] = os.environ) -> Path:
    """Return the path the environment sets for *key*.

    Args:
        key: PIN_FILE_KEY or PIN_ROOT_KEY.
        environ: the environment to read.

    Raises:
        PinError: the key is unset, so `.env` predates the pin.
    """
    value = environ.get(key, "").strip()
    if not value:
        raise PinError(f"{key} is not set; run `make dotenv`")
    return Path(value)


def validate(sha: str) -> str:
    """Return *sha* when it is a full commit id.

    Args:
        sha: the candidate commit id.

    Raises:
        PinError: an abbreviated id, a ref name or anything not hexadecimal.
    """
    candidate = sha.strip()
    if not FULL_SHA.fullmatch(candidate):
        raise PinError(f"'{sha}' is not a full commit id")
    return candidate


def resolve(ref: str, cwd: Path) -> str:
    """Return the full commit *ref* names in the repository at *cwd*.

    Args:
        ref: a branch, tag or commit id.
        cwd: a checkout of the repository.

    Raises:
        PinError: *ref* names no commit, for example a tree or a blob.
    """
    if not ref.strip() or ref.startswith("-"):
        raise PinError(f"'{ref}' is not a commit")
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PinError(f"'{ref}' is not a commit")
    return validate(result.stdout)


def read(path: Path) -> str:
    """Return the pinned commit.

    Args:
        path: the pin file.

    Raises:
        PinError: no pin exists yet, or the file holds no full commit id.
    """
    if not path.is_file():
        raise PinError(f"no cache pin at {path}; {DECLARE_HINT}")
    try:
        return validate(path.read_text(encoding="utf-8"))
    except PinError as exc:
        raise PinError(f"{path} holds no valid pin ({exc}); {DECLARE_HINT}") from exc


def _write(path: Path, sha: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{os.getpid()}")
    scratch.write_text(f"{sha}\n", encoding="utf-8")
    scratch.replace(path)
    return sha


def write(path: Path, sha: str) -> str:
    """Pin *sha* atomically and return it.

    Args:
        path: the pin file.
        sha: the full commit id.

    Raises:
        PinError: *sha* is not a full commit id.
    """
    return _write(path, validate(sha))


def applied_path(path: Path) -> Path:
    """Return the file that records the commit last applied to the stack.

    Args:
        path: the pin file.
    """
    return path.with_suffix(APPLIED_SUFFIX)


def read_applied(path: Path) -> str:
    """Return the commit last applied, empty when none was.

    Args:
        path: the pin file.
    """
    record = applied_path(path)
    if not record.is_file():
        return ""
    return record.read_text(encoding="utf-8").strip()


def write_applied(path: Path, sha: str) -> str:
    """Record *sha* as the commit last applied to the stack.

    Args:
        path: the pin file.
        sha: the full commit id.
    """
    return _write(applied_path(path), validate(sha))


def checkout(root: Path, sha: str) -> Path:
    """Return the directory the commit *sha* is materialized in.

    Args:
        root: INFINITO_CACHE_PIN_ROOT.
        sha: the full commit id.
    """
    return root / validate(sha)


def declare(path: Path, root: Path, sha: str) -> list[Path]:
    """Pin *sha*, then prune every checkout but the new and the previous pin.

    Args:
        path: the pin file.
        root: INFINITO_CACHE_PIN_ROOT.
        sha: the full commit id.

    Returns:
        The checkouts that were removed.

    Raises:
        PinError: *sha* is not a full commit id.
    """
    try:
        previous = read(path)
    except PinError:
        previous = ""
    write(path, sha)
    return prune(root, {sha, previous})


def prune(root: Path, keep: Iterable[str]) -> list[Path]:
    """Remove every full-commit-id directory below *root* not named in *keep*.

    Args:
        root: INFINITO_CACHE_PIN_ROOT.
        keep: the commit ids whose checkouts stay.

    Returns:
        The checkouts that were removed.
    """
    kept = set(keep)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.name in kept or not FULL_SHA.fullmatch(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed.append(entry)
    return removed


def status(environ: Mapping[str, str]) -> dict:
    """Return the pin row `make cache-status` prints.

    Args:
        environ: the environment to read the pin paths from.

    Returns:
        ``cache: pin`` with the pin file, the pinned and the applied commit,
        the checkout of the pin and whether it exists; ``error`` names what is
        missing, with the pinned commit then ``None``.
    """
    row: dict = {
        "cache": "pin",
        "pin_file": environ.get(PIN_FILE_KEY, ""),
        "pin": None,
        "applied": None,
        "checkout": None,
        "checkout_present": False,
        "error": None,
    }
    try:
        path = env_path(PIN_FILE_KEY, environ)
        row["applied"] = read_applied(path) or None
        row["pin"] = read(path)
        directory = checkout(env_path(PIN_ROOT_KEY, environ), row["pin"])
    except PinError as exc:
        row["error"] = str(exc)
        return row
    row["checkout"] = str(directory)
    row["checkout_present"] = directory.is_dir()
    return row


def pinned_declarations(directory: Path) -> dict:
    """Args:
        directory: a materialized checkout of the pin.

    Returns:
        ``{"repos": {...}, "hosts": {...}, "artefacts": {...}}`` as the code
        of *directory* reads its own declarations; a commit older than the
        ``artefacts`` key lacks it.
    """
    result = subprocess.run(
        [sys.executable, "-m", "cli.meta.cache.pin", "declarations"],
        cwd=directory,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _pinned_checkout(environ: Mapping[str, str]) -> Path:
    directory = checkout(
        env_path(PIN_ROOT_KEY, environ), read(env_path(PIN_FILE_KEY, environ))
    )
    if not directory.is_dir():
        raise PinError(f"the checkout {directory} of the pin is missing")
    return directory


def served_hosts(environ: Mapping[str, str]) -> dict | None:
    """Args:
        environ: the environment to read the pin paths from.

    Returns:
        The host records the pinned checkout declares. None while the
        environment names no pin file, so every own host is hijacked. Empty,
        with a warning on stderr, while the named pin, its checkout or its
        declarations cannot be read, so no host is hijacked.
    """
    if not environ.get(PIN_FILE_KEY, "").strip():
        return None
    try:
        return pinned_declarations(_pinned_checkout(environ))["hosts"]
    except UNREADABLE as exc:
        print(
            f"[cache-pin] WARNING: {exc}; no host is hijacked to the cache frontend",
            file=sys.stderr,
        )
        return {}


def pinned_digests(environ: Mapping[str, str]) -> frozenset[str] | None:
    """Args:
        environ: the environment to read the pin paths from.

    Returns:
        The sha256 of every artefact the pinned commit declares. Empty while
        no pin exists, because then no commit is pinned. None, with a warning
        on stderr, while the pin's checkout or its declarations cannot be
        read, so a caller cannot tell which stored artefact is still declared.
    """
    named = environ.get(PIN_FILE_KEY, "").strip()
    if not named or not Path(named).is_file():
        return frozenset()
    try:
        declared = pinned_declarations(_pinned_checkout(environ)).get(ARTEFACTS) or {}
        return frozenset(str(entry["sha256"]) for entry in declared.values())
    except (*UNREADABLE, AttributeError, TypeError) as exc:
        print(
            f"[cache-pin] WARNING: {exc}; the pinned artefacts are unknown",
            file=sys.stderr,
        )
        return None


def _comparable(records: dict) -> dict:
    return {
        name: {
            k: v
            for k, v in {
                **(HOST_DEFAULTS if "host" in record else {}),
                **record,
            }.items()
            if k not in IGNORED_FIELDS
        }
        for name, record in json.loads(json.dumps(records, sort_keys=True)).items()
    }


def agreed(own: dict, pinned: dict) -> set[str]:
    """Args:
        own: the host records of the calling checkout.
        pinned: the host records of the pinned commit.

    Returns:
        The hosts *pinned* declares exactly as *own* does, so the frontend
        has their server block and certificate.
    """
    mine = _comparable(own)
    theirs = _comparable(pinned)
    return {name for name, record in mine.items() if theirs.get(name) == record}


def drift(own: dict, pinned: dict) -> list[str]:
    """Return one line per declaration that differs from the pinned one.

    Args:
        own: ``{"repos": {...}, "hosts": {...}}`` of the calling checkout.
        pinned: the same shape for the pinned commit.
    """
    lines: list[str] = []
    for kind in ("repos", "hosts"):
        mine = _comparable(own.get(kind) or {})
        theirs = _comparable(pinned.get(kind) or {})
        for name in sorted(set(mine) | set(theirs)):
            if name not in theirs:
                lines.append(f"{kind[:-1]} {name}: declared here, not pinned")
            elif name not in mine:
                lines.append(f"{kind[:-1]} {name}: pinned, not declared here")
            elif mine[name] != theirs[name]:
                lines.append(f"{kind[:-1]} {name}: declared differently here")
    return lines
