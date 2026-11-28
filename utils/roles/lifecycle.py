from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.env.runtime import detect_gha_act
from utils.yaml_bootstrap import load_block

if TYPE_CHECKING:
    from pathlib import Path

FILE_META_LIFECYCLE: str = "meta/lifecycle.yml"
ENVELOPE_KEY = "INFINITO_LIFECYCLES"

CI_DEPLOY = "ci-deploy"
IMAGE_MIRROR = "image-mirror"
VERSION_UPDATE = "version-update"
UPDATE_CHECK_WARN = "update-check-warn"
UPDATE_CHECK_FAIL = "update-check-fail"
EOL_LABEL = "eol-label"
ACTIONS = frozenset(
    {IMAGE_MIRROR, VERSION_UPDATE, UPDATE_CHECK_WARN, UPDATE_CHECK_FAIL, EOL_LABEL}
)

PRODUCTION = "production"
RETIRED = "retired"
FLAGS = frozenset({PRODUCTION, RETIRED})

_TOP_KEYS = frozenset({"contexts", "statuses", "migrations"})
_STATUS_KEYS = frozenset({"description", "predecessors", "flags", CI_DEPLOY, "actions"})
_CRITERIA = ("repository", "refs", "events")


class LifecycleError(ValueError):
    """Raised when ``meta/lifecycle.yml`` violates its declared shape."""


@dataclass(frozen=True)
class Context:
    """One CI trigger context.

    Attributes:
        name: the key the statuses' ``ci-deploy`` lists name.
        description: which runs the context covers.
        repository: the ``GITHUB_REPOSITORY`` a run must come from, ``None``
            for the fallback context.
        refs: the ``GITHUB_REF`` values a run may carry.
        events: the ``GITHUB_EVENT_NAME`` values a run may carry.
    """

    name: str
    description: str
    repository: str | None
    refs: tuple[str, ...]
    events: tuple[str, ...]


@dataclass(frozen=True)
class Status:
    """One declared status.

    Attributes:
        name: the value a role's ``lifecycle`` key carries.
        description: what the status means for the role and its consumers.
        predecessors: statuses a role may move here from.
        flags: reference-rule flags, a subset of :data:`FLAGS`.
        ci_deploy: the contexts whose CI deploys a role in this status.
        actions: what the system does with the role, a subset of
            :data:`ACTIONS`.
    """

    name: str
    description: str
    predecessors: tuple[str, ...]
    flags: frozenset[str]
    ci_deploy: frozenset[str]
    actions: frozenset[str]


@dataclass(frozen=True, eq=False)
class Lifecycle:
    """The validated file.

    Attributes:
        order: every status name in the order derived from the predecessors.
        statuses: status name to :class:`Status`.
        contexts: context name to :class:`Context`, in file order.
        migrations: consumer role to ``{target role: reason}``.
    """

    order: tuple[str, ...]
    statuses: dict[str, Status]
    contexts: dict[str, Context]
    migrations: dict[str, dict[str, str]]

    def with_action(self, action: str) -> frozenset[str]:
        """Statuses whose ``actions`` carry *action*."""
        return frozenset(n for n, s in self.statuses.items() if action in s.actions)

    def without_action(self, action: str) -> frozenset[str]:
        """Declared statuses whose ``actions`` lack *action*."""
        return frozenset(self.statuses) - self.with_action(action)

    def with_flag(self, flag: str) -> frozenset[str]:
        """Statuses whose ``flags`` carry *flag*."""
        return frozenset(n for n, s in self.statuses.items() if flag in s.flags)

    def deployed_in(self, context: str) -> frozenset[str]:
        """Statuses whose ``ci-deploy`` names *context*."""
        return frozenset(n for n, s in self.statuses.items() if context in s.ci_deploy)

    def deployed(self) -> frozenset[str]:
        """Statuses some context deploys."""
        return frozenset(n for n, s in self.statuses.items() if s.ci_deploy)

    def ordered(self, names: frozenset[str]) -> tuple[str, ...]:
        """*names* in the derived lifecycle order."""
        return tuple(name for name in self.order if name in names)

    def beyond_production(self) -> frozenset[str]:
        """Statuses that sort after every production status."""
        production = self.with_flag(PRODUCTION)
        last = max((self.order.index(n) for n in production), default=-1)
        return frozenset(self.order[last + 1 :]) - production

    def context_of(
        self,
        *,
        on_github: bool,
        repository: str | None,
        ref: str | None,
        event: str | None,
    ) -> str:
        """The context a run belongs to.

        Args:
            on_github: whether the run is a real GitHub Actions run, not act.
            repository: its ``GITHUB_REPOSITORY``.
            ref: its ``GITHUB_REF``.
            event: its ``GITHUB_EVENT_NAME``.
        """
        fallback = next(c.name for c in self.contexts.values() if c.repository is None)
        if not on_github:
            return fallback
        return next(
            (
                c.name
                for c in self.contexts.values()
                if c.repository is not None
                and c.repository == repository
                and ref in c.refs
                and event in c.events
            ),
            fallback,
        )

    def forbidden(self, consumer: str | None, target: str | None) -> str | None:
        """Why the reference rule forbids a *consumer* role referencing *target*.

        Args:
            consumer: the referencing role's status, ``None`` when it has none.
            target: the referenced role's status, ``None`` when it has none.

        Returns:
            The broken rule as a phrase, or ``None`` when the reference is
            allowed.
        """
        if target in self.with_flag(RETIRED):
            return f"'{target}' is {RETIRED}, so no role may reference it"
        if (
            consumer in self.with_flag(PRODUCTION)
            and target in self.beyond_production()
        ):
            return (
                f"'{consumer}' is {PRODUCTION} and '{target}' sorts beyond "
                f"every {PRODUCTION} status"
            )
        return None


def lifecycle_file(root: Path | None = None) -> Path:
    """Absolute path of ``meta/lifecycle.yml`` below *root*.

    Args:
        root: tree to resolve against; the repository root when omitted.
    """
    return (PROJECT_ROOT if root is None else root) / FILE_META_LIFECYCLE


def _names(entry: dict, key: str, owner: str, errors: list[str]) -> tuple[str, ...]:
    raw = entry.get(key, [])
    if not isinstance(raw, list):
        errors.append(f"{owner}.{key} must be a block list")
        return ()
    return tuple(raw)


def _description(entry: dict, owner: str, errors: list[str]) -> str:
    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{owner} needs a one-sentence description")
        return ""
    return description


def _parse_status(name: str, entry: object, errors: list[str]) -> Status | None:
    owner = f"statuses.{name}"
    if not isinstance(entry, dict):
        errors.append(f"{owner} must be a mapping")
        return None
    errors.extend(
        f"{owner} carries unknown key '{key}'"
        for key in sorted(set(entry) - _STATUS_KEYS)
    )
    flags = frozenset(_names(entry, "flags", owner, errors))
    actions = frozenset(_names(entry, "actions", owner, errors))
    errors.extend(
        f"{owner} names unknown flag '{flag}'" for flag in sorted(flags - FLAGS)
    )
    errors.extend(
        f"{owner} names unknown action '{action}'"
        for action in sorted(actions - ACTIONS)
    )
    if flags >= FLAGS:
        errors.append(f"{owner} cannot be both {PRODUCTION} and {RETIRED}")
    return Status(
        name=name,
        description=_description(entry, owner, errors),
        predecessors=_names(entry, "predecessors", owner, errors),
        flags=flags,
        ci_deploy=frozenset(_names(entry, CI_DEPLOY, owner, errors)),
        actions=actions,
    )


def _parse_context(name: str, entry: object, errors: list[str]) -> Context | None:
    owner = f"contexts.{name}"
    if not isinstance(entry, dict):
        errors.append(f"{owner} must be a mapping")
        return None
    errors.extend(
        f"{owner} carries unknown key '{key}'"
        for key in sorted(set(entry) - {"description", *_CRITERIA})
    )
    declared = [key for key in _CRITERIA if key in entry]
    if declared and len(declared) != len(_CRITERIA):
        errors.append(f"{owner} must declare all of {', '.join(_CRITERIA)} or none")
    repository = entry.get("repository")
    if declared and not isinstance(repository, str):
        errors.append(f"{owner}.repository must be a string")
    return Context(
        name=name,
        description=_description(entry, owner, errors),
        repository=repository if isinstance(repository, str) else None,
        refs=_names(entry, "refs", owner, errors),
        events=_names(entry, "events", owner, errors),
    )


def _parse_contexts(raw: object, errors: list[str]) -> dict[str, Context]:
    if not isinstance(raw, dict) or not raw:
        errors.append("contexts must be a non-empty mapping")
        return {}
    contexts = {
        name: context
        for name, entry in raw.items()
        if (context := _parse_context(name, entry, errors)) is not None
    }
    fallbacks = sorted(n for n, c in contexts.items() if c.repository is None)
    if len(fallbacks) != 1:
        errors.append(
            f"exactly one context without criteria is required, found "
            f"{len(fallbacks)}: {', '.join(fallbacks) or '-'}"
        )
    return contexts


def derive_order(statuses: dict[str, Status]) -> tuple[tuple[str, ...], list[str]]:
    """Topologically sort *statuses* along their predecessor edges.

    Args:
        statuses: status name to :class:`Status`.

    Returns:
        ``(order, errors)``. The order holds every status the sort reached.
        Errors name every unknown predecessor, an entry count other than one,
        a step where more than one status could come next, a cycle, and every
        status the entry cannot reach.
    """
    errors = [
        f"statuses.{name} names unknown predecessor '{pred}'"
        for name, status in statuses.items()
        for pred in status.predecessors
        if pred not in statuses
    ]
    entries = sorted(n for n, s in statuses.items() if not s.predecessors)
    if len(entries) != 1:
        errors.append(
            f"exactly one entry status without predecessors is required, found "
            f"{len(entries)}: {', '.join(entries) or '-'}"
        )
    successors: dict[str, set[str]] = {name: set() for name in statuses}
    pending = dict.fromkeys(statuses, 0)
    for name, status in statuses.items():
        for pred in set(status.predecessors) & set(statuses):
            successors[pred].add(name)
            pending[name] += 1
    order: list[str] = []
    ready = sorted(n for n, count in pending.items() if count == 0)
    while ready:
        if len(ready) > 1:
            errors.append(
                f"the order is not unique: {', '.join(ready)} could each come "
                f"next; add a predecessor edge between them"
            )
        current = ready.pop(0)
        order.append(current)
        for succ in sorted(successors[current]):
            pending[succ] -= 1
            if pending[succ] == 0:
                ready.append(succ)
        ready.sort()
    cyclic = sorted(set(statuses) - set(order))
    if cyclic:
        errors.append(f"the predecessor graph has a cycle through {', '.join(cyclic)}")
    reached = set(entries)
    frontier = list(entries)
    while frontier:
        for succ in successors[frontier.pop()]:
            if succ not in reached:
                reached.add(succ)
                frontier.append(succ)
    unreachable = sorted(set(statuses) - reached)
    if unreachable and entries:
        errors.append(f"no path from the entry reaches {', '.join(unreachable)}")
    return tuple(order), errors


def _parse_migrations(raw: object, errors: list[str]) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors.append("migrations must be a mapping of consumer role to targets")
        return {}
    migrations: dict[str, dict[str, str]] = {}
    for consumer, targets in raw.items():
        if not isinstance(targets, dict):
            errors.append(f"migrations.{consumer} must map target role to reason")
            continue
        errors.extend(
            f"migrations.{consumer}.{target} needs a reason"
            for target, reason in targets.items()
            if not isinstance(reason, str) or not reason.strip()
        )
        migrations[consumer] = {t: r for t, r in targets.items() if isinstance(r, str)}
    return migrations


def parse(spec: object) -> tuple[Lifecycle, list[str]]:
    """Build a :class:`Lifecycle` from the loaded file, collecting every error.

    Args:
        spec: the mapping ``meta/lifecycle.yml`` loads to.

    Returns:
        ``(lifecycle, errors)``.
    """
    errors: list[str] = []
    if not isinstance(spec, dict):
        return Lifecycle((), {}, {}, {}), ["the file must be a mapping"]
    errors.extend(
        f"unknown top-level key '{key}'" for key in sorted(set(spec) - _TOP_KEYS)
    )
    contexts = _parse_contexts(spec.get("contexts"), errors)
    raw = spec.get("statuses")
    if not isinstance(raw, dict) or not raw:
        errors.append("statuses must be a non-empty mapping")
        raw = {}
    statuses = {
        name: status
        for name, entry in raw.items()
        if (status := _parse_status(name, entry, errors)) is not None
    }
    errors.extend(
        f"statuses.{name}.{CI_DEPLOY} names unknown context '{context}'"
        for name, status in statuses.items()
        for context in sorted(status.ci_deploy - set(contexts))
    )
    order, graph_errors = derive_order(statuses)
    errors.extend(graph_errors)
    migrations = _parse_migrations(spec.get("migrations"), errors)
    return Lifecycle(order, statuses, contexts, migrations), errors


@cache
def load(root: Path | None = None) -> Lifecycle:
    """The validated ``meta/lifecycle.yml`` below *root*.

    Args:
        root: tree to resolve against; the repository root when omitted.

    Raises:
        LifecycleError: the file breaks its declared shape.
    """
    path = lifecycle_file(root)
    lifecycle, errors = parse(load_block(read_text(str(path))))
    if errors:
        raise LifecycleError(f"{path}: " + "; ".join(errors))
    return lifecycle


def statuses() -> tuple[str, ...]:
    """Every declared status in the derived lifecycle order."""
    return load().order


def tested_lifecycles() -> frozenset[str]:
    """Statuses some CI trigger context deploys by default."""
    return load().deployed()


def current_context() -> str:
    """The context of this process, from the GitHub Actions environment."""
    on_github, _ = detect_gha_act()
    return load().context_of(
        on_github=on_github,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        ref=os.environ.get("GITHUB_REF"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
    )


def default_envelope(context: str, root: Path | None = None) -> str:
    """The ``INFINITO_LIFECYCLES`` default of *context*, in lifecycle order.

    Args:
        context: a context name ``meta/lifecycle.yml`` declares.
        root: tree to resolve against; the repository root when omitted.
    """
    lifecycle = load(root)
    return " ".join(lifecycle.ordered(lifecycle.deployed_in(context)))


def envelope() -> str:
    """The run's envelope: the process environment wins over its context default."""
    raw = os.environ.get(ENVELOPE_KEY)
    return (
        raw if raw is not None and raw.strip() else default_envelope(current_context())
    )
