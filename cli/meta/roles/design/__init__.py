"""Work queue of the corporate-design routine.

A role is a candidate when it is a ``web-app-`` or ``web-svc-`` role with a web
UI of its own and its lifecycle sits inside the tested envelope. Every
candidate carries exactly one state:

* ``review``: its design spec is untracked or modified and waits for approval.
* ``new``: HEAD carries no design spec for it.
* ``stale``: the image version or the shared design base moved since the last
  commit of its design spec.
* ``current``: nothing moved since then.

``new`` and ``stale`` roles are due, in that order.

CLI: ``python -m cli.meta.roles.design --help``
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_str
from utils.roles.applications.services.registry import read_yaml_file
from utils.roles.entity.name import entity_name
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_PLAYWRIGHT_SPEC
from utils.roles.meta_lookup import get_role_lifecycle

if TYPE_CHECKING:
    from collections.abc import Callable

Gap = tuple[int, int, int]

SPEC_FILE = (
    PurePosixPath(ROLE_FILE_PLAYWRIGHT_SPEC).with_name("test-design.js").as_posix()
)
BASE_PATHS: tuple[str, ...] = (
    "roles/sys-front-inj-design/templates/css",
    "utils/design/palette.py",
)
UI_PREFIXES: tuple[str, ...] = ("web-app-", "web-svc-")
UI_LESS_ROLES: frozenset[str] = frozenset(
    {
        "web-svc-asset",
        "web-svc-cdn",
        "web-svc-coturn",
        "web-svc-design",
        "web-svc-file",
        "web-svc-mirror",
        "web-svc-simpleicons",
        "web-svc-xmpp",
    }
)

STATE_REVIEW = "review"
STATE_NEW = "new"
STATE_STALE = "stale"
STATE_CURRENT = "current"

NO_GAP: Gap = (0, 0, 0)
MINIMAL_GAP: Gap = (0, 0, 1)

_LEADING_NUMBER_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


class GitError(RuntimeError):
    """Raised when git is missing or a git command fails."""


@dataclass(frozen=True)
class DesignCommit:
    """Last commit of a design spec: full hash and commit time in epoch seconds."""

    sha: str
    timestamp: int


@dataclass(frozen=True)
class RoleFacts:
    """Git and working-tree facts of one candidate role.

    Args:
        role: Role directory name.
        created: Commit time of the oldest commit reachable from HEAD that
            changed a file below ``roles/<role>``, ``None`` when no commit did.
            The whole directory is read instead of the commit that added one
            file, so a file that was removed and added again cannot reset it.
        changed: Commit time of the newest such commit, ``None`` when none.
        designed: Last commit that touched the design spec, ``None`` when HEAD
            carries no design spec.
        in_review: Whether the design spec exists in the working tree and is
            untracked or has uncommitted changes.
        base_changed: Whether a commit that ``designed`` does not contain
            touched the shared design base. Ancestry decides instead of the
            commit time, so a rebase that stamps both commits with the same
            second cannot hide a base change.
        designed_version: Image version of the primary entity at ``designed``.
        current_version: Image version of the primary entity in the working
            tree. Both versions are ``None`` when undeclared.
    """

    role: str
    created: int | None
    changed: int | None
    designed: DesignCommit | None
    in_review: bool
    base_changed: bool
    designed_version: str | None
    current_version: str | None

    @property
    def version_gap(self) -> Gap:
        """Distance the image version moved since the last design pass."""
        if self.designed is None:
            return NO_GAP
        return version_gap(self.designed_version, self.current_version)


@dataclass(frozen=True)
class QueueEntry:
    """One row of the design queue.

    Args:
        rank: Position in the due queue, counted from 1, ``None`` when not due.
        role: Role directory name.
        state: ``new``, ``stale``, ``review`` or ``current``.
        reason: Why the role carries that state.
        version_gap: ``(major, minor, patch)`` distance of the image version.
        created: ``RoleFacts.created`` in Unix epoch seconds.
        changed: ``RoleFacts.changed`` in Unix epoch seconds.
    """

    rank: int | None
    role: str
    state: str
    reason: str
    version_gap: Gap
    created: int | None
    changed: int | None


def _leading_number(version: str | None) -> Gap | None:
    match = _LEADING_NUMBER_RE.match(version) if version else None
    if match is None:
        return None
    parts = [int(part) for part in match.group(1).split(".")][:3]
    major, minor, patch = (*parts, *([0] * (3 - len(parts))))
    return (major, minor, patch)


def version_gap(designed: str | None, current: str | None) -> Gap:
    """Measure how far an image version moved.

    Both versions lose a leading ``v`` and are read up to the end of their
    leading dotted number, padded or cut to three components.

    Args:
        designed: Version at the last design pass, ``None`` when undeclared.
        current: Version in the working tree, ``None`` when undeclared.

    Returns:
        The absolute ``(major, minor, patch)`` differences, ``(0, 0, 0)`` for
        equal versions and ``(0, 0, 1)`` for versions that differ without a
        numeric distance: one side is missing or not numeric, or the change
        sits behind the third component.
    """
    if designed == current:
        return NO_GAP
    old, new = _leading_number(designed), _leading_number(current)
    if old is None or new is None:
        return MINIMAL_GAP
    major, minor, patch = (abs(a - b) for a, b in zip(old, new, strict=True))
    gap = (major, minor, patch)
    return gap if gap != NO_GAP else MINIMAL_GAP


def state_of(facts: RoleFacts) -> str:
    """Return the state of a candidate: review, new, stale or current."""
    if facts.in_review:
        return STATE_REVIEW
    if facts.designed is None:
        return STATE_NEW
    if facts.base_changed or facts.version_gap != NO_GAP:
        return STATE_STALE
    return STATE_CURRENT


def _shown(version: str | None) -> str:
    return "none" if version is None else version


def reason_of(facts: RoleFacts) -> str:
    """Return a short human-readable reason for the state of a candidate."""
    state = state_of(facts)
    if state == STATE_REVIEW:
        return "design spec awaits approval"
    if state == STATE_NEW:
        return "never designed"
    if state == STATE_CURRENT:
        return "up to date"
    reasons = []
    if facts.version_gap != NO_GAP:
        old, new = _shown(facts.designed_version), _shown(facts.current_version)
        reasons.append(f"version {old} -> {new}")
    if facts.base_changed:
        reasons.append("design base changed")
    return ", ".join(reasons)


def _newest_first(timestamp: int | None) -> tuple[bool, int]:
    if timestamp is None:
        return (True, 0)
    return (False, -timestamp)


def _new_order(facts: RoleFacts) -> tuple[object, ...]:
    return (_newest_first(facts.created), _newest_first(facts.changed), facts.role)


def _stale_order(facts: RoleFacts) -> tuple[object, ...]:
    major, minor, patch = facts.version_gap
    return ((-major, -minor, -patch), _newest_first(facts.changed), facts.role)


def _in_state(
    facts: list[RoleFacts], state: str, order: Callable[[RoleFacts], object]
) -> list[RoleFacts]:
    return sorted((item for item in facts if state_of(item) == state), key=order)


def _entry(facts: RoleFacts, rank: int | None) -> QueueEntry:
    return QueueEntry(
        rank=rank,
        role=facts.role,
        state=state_of(facts),
        reason=reason_of(facts),
        version_gap=facts.version_gap,
        created=facts.created,
        changed=facts.changed,
    )


def build_queue(facts: list[RoleFacts]) -> list[QueueEntry]:
    """Order the roles that are due for a design pass.

    Args:
        facts: Facts of every candidate role.

    Returns:
        The ``new`` roles, newest first, followed by the ``stale`` roles,
        largest version gap first. A tie falls to the most recently changed
        role and then to the role name. A role no commit touched sorts behind
        the committed ones. Ranks count from 1.
    """
    due = [
        *_in_state(facts, STATE_NEW, _new_order),
        *_in_state(facts, STATE_STALE, _stale_order),
    ]
    return [_entry(item, rank) for rank, item in enumerate(due, start=1)]


def not_due(facts: list[RoleFacts]) -> list[QueueEntry]:
    """List the ``review`` roles, then the ``current`` ones, without a rank.

    Args:
        facts: Facts of every candidate role.
    """
    by_name = attrgetter("role")
    idle = [
        *_in_state(facts, STATE_REVIEW, by_name),
        *_in_state(facts, STATE_CURRENT, by_name),
    ]
    return [_entry(item, None) for item in idle]


def _git(root: Path, *args: str, stdin: str | None = None) -> str:
    """Run a read-only git command in a directory and return its output.

    ``--no-optional-locks`` keeps ``git status`` from taking ``index.lock``,
    which would abort a commit that another process runs in the same tree.

    Raises:
        GitError: When the git binary is missing or the command exits non-zero.
    """
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=root,
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise GitError(f"cannot run git in {root}: {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"git {args[0]} failed in {root}: {result.stderr.strip()}")
    return result.stdout


def repository_root(start: Path) -> Path:
    """Resolve the root of the work tree that contains a directory.

    Raises:
        GitError: When git is unavailable or ``start`` is outside a work tree.
    """
    return Path(_git(start, "rev-parse", "--show-toplevel").strip())


def _primary_version(services: object, role: str) -> str | None:
    if not isinstance(services, dict):
        return None
    entry = services.get(entity_name(role))
    if not isinstance(entry, dict) or entry.get("version") is None:
        return None
    return str(entry["version"]).strip() or None


def _is_candidate(role_dir: Path, envelope: frozenset[str]) -> bool:
    role = role_dir.name
    if not role.startswith(UI_PREFIXES) or role in UI_LESS_ROLES:
        return False
    return get_role_lifecycle(role_dir, role_name=role) in envelope


def candidate_roles(roles_dir: Path) -> list[str]:
    """Select the roles that take part in the design queue.

    Args:
        roles_dir: Directory holding the roles.

    Returns:
        Sorted names of the ``web-app-`` and ``web-svc-`` roles that have a web
        UI of their own and carry a lifecycle inside the tested envelope. A
        role without a ``design`` service entry is included: its design pass
        adds the entry.
    """
    envelope = tested_lifecycles()
    return [
        role_dir.name
        for role_dir in sorted(roles_dir.iterdir())
        if role_dir.is_dir() and _is_candidate(role_dir, envelope)
    ]


def _spec(role: str) -> str:
    return f"roles/{role}/{SPEC_FILE}"


def _committed_specs(root: Path, roles: list[str]) -> set[str]:
    if not roles:
        return set()
    specs = [_spec(role) for role in roles]
    return set(_git(root, "ls-tree", "--name-only", "HEAD", "--", *specs).splitlines())


def _commit_times(root: Path) -> dict[str, list[int]]:
    """Map every role to the commit times of the commits that changed it.

    ``--full-history`` is load-bearing. The default history simplification
    follows a single parent of each merge, and in a shallow clone that walk
    ends at whichever boundary commit it reaches first: a boundary commit has
    no parent, so it counts as adding every file it carries. Roles that rarely
    change then report that boundary as their oldest commit and pass for the
    newest roles. A merge commit lists no files and never counts. Git wraps a
    path with unusual bytes in double quotes, hence the stripped leading quote.
    """
    commits = _git(root, "rev-list", "--full-history", "HEAD", "--", "roles")
    history = _git(
        root,
        "diff-tree",
        "--stdin",
        "--root",
        "-r",
        "--name-only",
        "--format=%x00%ct",
        "--",
        "roles",
        stdin=commits,
    )
    times: defaultdict[str, list[int]] = defaultdict(list)
    for record in history.split("\0")[1:]:
        commit_time, *paths = record.splitlines()
        for role in {path.lstrip('"').split("/")[1] for path in paths if path}:
            times[role].append(int(commit_time))
    return dict(times)


def _designed(root: Path, spec: str) -> DesignCommit | None:
    last = _git(root, "rev-list", "--timestamp", "-1", "HEAD", "--", spec).split()
    if not last:
        return None
    timestamp, sha = last
    return DesignCommit(sha=sha, timestamp=int(timestamp))


def _in_review(root: Path, spec: str) -> bool:
    """Tell whether the design spec is untracked or has uncommitted changes.

    ``--untracked-files=all`` overrides a ``status.showUntrackedFiles=no`` in
    the user configuration, which would hide a spec that was never added.
    """
    if not (root / spec).is_file():
        return False
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", spec)
    return bool(status.strip())


def _base_changed(root: Path, designed: DesignCommit) -> bool:
    newer = _git(root, "rev-list", "-1", f"{designed.sha}..HEAD", "--", *BASE_PATHS)
    return bool(newer.strip())


def _designed_version(root: Path, role: str, designed: DesignCommit) -> str | None:
    services = f"roles/{role}/{ROLE_FILE_META_SERVICES}"
    if not _git(root, "ls-tree", "--name-only", designed.sha, "--", services).strip():
        return None
    content = _git(root, "cat-file", "blob", f"{designed.sha}:{services}")
    return _primary_version(load_yaml_str(content), role)


def _role_facts(
    root: Path, role: str, times: list[int] | None, committed_specs: set[str]
) -> RoleFacts:
    spec = _spec(role)
    designed = _designed(root, spec) if spec in committed_specs else None
    services = read_yaml_file(root / "roles" / role / ROLE_FILE_META_SERVICES)
    return RoleFacts(
        role=role,
        created=min(times) if times else None,
        changed=max(times) if times else None,
        designed=designed,
        in_review=_in_review(root, spec),
        base_changed=designed is not None and _base_changed(root, designed),
        designed_version=(
            None if designed is None else _designed_version(root, role, designed)
        ),
        current_version=_primary_version(services, role),
    )


def collect_facts(repo_root: Path) -> list[RoleFacts]:
    """Collect the facts of every candidate role from git and the working tree.

    Args:
        repo_root: Root of the repository work tree.

    Returns:
        One entry per candidate role, sorted by role name.

    Raises:
        GitError: When git is unavailable or a git command fails.
    """
    roles = candidate_roles(repo_root / "roles")
    times = _commit_times(repo_root)
    committed_specs = _committed_specs(repo_root, roles)
    return [
        _role_facts(repo_root, role, times.get(role), committed_specs) for role in roles
    ]
