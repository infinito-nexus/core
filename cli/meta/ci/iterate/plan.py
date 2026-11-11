"""Assemble the iteration plan of one diff: tiers T0 to T3, the rows behind
them and every cut.

``roles`` lists every role the plan accounts for. Each sits in the T3
whitelist or in a cut of tier ``all``, and the baseline (what
``scripts/meta/resolve/diff/affected_roles.sh`` widens the same diff to) is
always a subset of the two: the classifier may narrow the fail-safe rule, but
only by naming each role it leaves out and the paths that let it. Cuts of a
narrower tier (``local``, ``T0``, ``T1``, ``T2``) name what a local tier
leaves to a later one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.meta.ci.iterate import commands, tiers
from cli.meta.ci.iterate.budget import price
from cli.meta.ci.iterate.classify import DOC_SEED, FULL, NONE, SEED
from cli.meta.ci.iterate.surface import (
    DOC_SUFFIXES,
    DOCS,
    PLUGIN,
    WORKFLOW,
    WORKFLOWS,
)

if TYPE_CHECKING:
    from cli.meta.ci.iterate.catalog import Catalog
    from cli.meta.ci.iterate.classify import Change

ALL = "__ALL__"
AUTO = "auto"
LOOPS = (AUTO, "compose", "swarm", "playwright", "workflow", "runner")
RUNNER_ROLE = "svc-runner"
NONE_DISABLE = "none"
DEFAULT_DISABLE = ("matomo", "dashboard", "prometheus", "email", "design")
NON_PYTHON_TESTS = ("javascript", "php", "ruby")
WORKFLOW_LINT = "workflow"
MAKEFILE_LINT = "Makefile"
DOCKERFILE_LINT = "Dockerfile"
LINTERS = {
    WORKFLOW_LINT: ("make lint-action",),
    MAKEFILE_LINT: ("make lint-makefile",),
    DOCKERFILE_LINT: ("make lint-dockerfile",),
    ".py": ("ruff check {files}", "ruff format --check {files}"),
    ".sh": ("shellcheck {files}",),
    ".md": ("make lint-markdown",),
    ".js": ("make lint-javascript",),
    ".css": ("make lint-css",),
    ".php": ("make lint-php",),
    ".rb": ("make lint-ruby",),
    ".sql": ("make lint-sql",),
    ".yml": ("make lint-ansible",),
    ".yaml": ("make lint-ansible",),
}
SUITE_CUT = (
    "a tests/lint or tests/integration test runs in T0 only where it consumes "
    "a changed module or path, and a unit test reading the roles tree only "
    "where it names a changed role; the T2 gate make test runs them all"
)
UNCHECKED_CUT = (
    "no test, make target, role or deploy names these paths; "
    "nothing in the plan exercises them"
)
EXTERNAL = "tests/external/"
EXTERNAL_CUT = (
    "tests/external reaches live third-party systems and is opt-in; "
    "make test-external runs it"
)
PYTEST = "PYTHONPATH=. python3 -m pytest --import-mode=importlib -q "


def baseline_widens(paths: list[str]) -> bool:
    """Return True where ``affected_roles.sh`` answers ``__ALL__`` on its path rule.

    It does for an empty diff and for any path outside ``roles/<role>/`` that
    is neither a Markdown or reStructuredText file nor under ``tests/``.
    """
    if not paths:
        return True
    return any(
        not (p.startswith("roles/") and p.count("/") >= 2)
        and not p.endswith(DOC_SUFFIXES)
        and not p.startswith("tests/")
        for p in paths
    )


def seeded_role(path: str, roles: frozenset[str]) -> str:
    """Return the role a test path seeds in ``affected_roles.sh``, else empty.

    A path under ``tests/`` seeds the role named by the segment after its
    first ``/roles/``, when that role exists.

    Args:
        path: repository-relative POSIX path.
        roles: every role of the checkout.
    """
    if not path.startswith("tests/"):
        return ""
    _, marker, rest = path.partition("/roles/")
    role, slash, _ = rest.partition("/")
    return role if marker and slash and role in roles else ""


def token_roles(tokens: list[str]) -> set[str]:
    """Return the roles a list of selection tokens names."""
    return {tiers.split_token(token)[0] for token in tokens}


def accounted(result: dict) -> set[str]:
    """Return every role a plan places in the T3 whitelist or in a cut of tier ``all``.

    The baseline of the same diff is a subset of it by construction; a role
    outside it would be one the plan dropped without naming.

    Args:
        result: the dict :func:`build` returns.
    """
    whitelist = result["tiers"]["T3"]["whitelist"]
    placed = (
        set(result["roles"]) if whitelist == ALL else token_roles(whitelist.split())
    )
    return placed | {
        role for cut in result["cuts"] if cut["tier"] == "all" for role in cut["roles"]
    }


def _baseline(paths: list[str], catalog: Catalog) -> tuple[set[str], str]:
    if baseline_widens(paths):
        return set(catalog.roles), "affected_roles.sh widens this diff to __ALL__"
    known = frozenset(catalog.roles)
    seeds = {p.split("/", 2)[1] for p in paths if p.startswith("roles/")} | {
        role for p in paths if (role := seeded_role(p, known))
    }
    if not seeds:
        return set(
            catalog.roles
        ), "affected_roles.sh widens a diff without role seeds to __ALL__"
    tokens, refused = catalog.affected(seeds)
    if refused:
        return set(catalog.roles), f"affected_roles.sh falls back to __ALL__: {refused}"
    return token_roles(tokens), "affected_roles.sh closure of the role paths"


def _narrows(change: Change) -> bool:
    if change.effect == FULL:
        return False
    if change.path.startswith("roles/"):
        return change.effect != SEED or change.kind == PLUGIN
    return not change.path.endswith(DOC_SUFFIXES) and not change.path.startswith(
        "tests/"
    )


def resolve_disable(
    requested: str, seeds: set[str], catalog: Catalog
) -> tuple[list[str], dict[str, str]]:
    """Return the provider keys to render disabled and the ones kept on.

    Args:
        requested: comma-separated keys; empty proposes the compose loop's
            default, ``none`` disables nothing.
        seeds: the roles under test; a key one of them provides stays on.
        catalog: the roles tree facts.
    """
    if requested.strip() == NONE_DISABLE:
        return [], {}
    keys = [k.strip() for k in requested.split(",") if k.strip()]
    kept = {
        key: f"provided by {catalog.provider(key)}, a role under test"
        for key in keys or DEFAULT_DISABLE
        if catalog.provider(key) in seeds
    }
    return [key for key in keys or DEFAULT_DISABLE if key not in kept], kept


def choose_loop(
    requested: str,
    changes: list[Change],
    seeds: list[str],
    catalog: Catalog,
    *,
    deploy_paths: list[str],
    full: bool,
) -> str:
    """Return the iteration loop: the operator's, else the one the diff needs.

    Args:
        requested: ``auto`` or empty derives it, anything else is kept.
        changes: the classified paths.
        seeds: the roles under test.
        catalog: the roles tree facts.
        deploy_paths: the changed paths that reach a deploy.
        full: the diff reaches every deploy.
    """
    if requested and requested != AUTO:
        return requested
    if RUNNER_ROLE in seeds:
        return "runner"
    if seeds and commands.spec_only(deploy_paths):
        return "playwright"
    rows = [row for seed in seeds for row in catalog.rows(seed)]
    if rows and not any(r.compose for r in rows) and any(r.swarm for r in rows):
        return "swarm"
    if seeds or full:
        return "compose"
    if any(c.kind == WORKFLOW for c in changes):
        return "workflow"
    return "none"


def lint_key(path: str) -> str:
    """Return the :data:`LINTERS` key of *path*, empty when no linter covers it.

    Args:
        path: repository-relative POSIX path.
    """
    name = path.rpartition("/")[2]
    if path.startswith(WORKFLOWS):
        return WORKFLOW_LINT
    if name == MAKEFILE_LINT or name.endswith(".mk"):
        return MAKEFILE_LINT
    if name.startswith(DOCKERFILE_LINT):
        return DOCKERFILE_LINT
    return next((s for s in LINTERS if s.startswith(".") and name.endswith(s)), "")


def _is_python_test(path: str) -> bool:
    parts = path.split("/")
    return len(parts) < 3 or parts[2] not in NON_PYTHON_TESTS


def unit_tier(changes: list[Change], seeds: list[str], catalog: Catalog) -> dict:
    """Return T0: the test files and the lint commands of the diff, and the
    tooling make targets that run a changed file, listed for the agent to
    pick since a target may be interactive or reach a live service.

    A test path the diff deleted runs as its directory, while that exists.

    Args:
        changes: the classified paths.
        seeds: the roles under test, whose role unit tests run too.
        catalog: the roles tree facts.
    """
    wanted = {t for c in changes for t in c.tests} | {
        t for seed in seeds for t in catalog.unit_tests(seed)
    }
    present = {t if catalog.exists(t) else t.rpartition("/")[0] for t in wanted}
    tests = sorted(t for t in present if t and catalog.exists(t))
    external = [t for t in tests if t.startswith(EXTERNAL)]
    python = [t for t in tests if _is_python_test(t) and t not in external]
    python = [t for t in python if not any(t.startswith(f"{d}/") for d in python)]
    lines = [PYTEST + " ".join(python)] if python else []
    lines += [
        f"make test-unit-{language}"
        for language in NON_PYTHON_TESTS
        if any(t.startswith(f"tests/unit/{language}/") for t in tests)
    ]
    lint: dict[str, list[str]] = {}
    for change in changes:
        suffix = lint_key(change.path)
        if suffix and catalog.exists(change.path):
            lint.setdefault(suffix, []).append(change.path)
    for suffix, files in sorted(lint.items()):
        lines += [line.format(files=" ".join(files)) for line in LINTERS[suffix]]
    return {
        "tests": tests,
        "external": external,
        "lint": dict(sorted(lint.items())),
        "commands": lines,
        "targets": sorted({f"make {t}" for c in changes for t in c.targets}),
    }


def build(
    paths: list[str],
    changes: list[Change],
    catalog: Catalog,
    *,
    loop: str,
    disable: str,
    timings: str,
) -> dict:
    """Return the plan of one diff.

    Args:
        paths: every changed path.
        changes: their classification, one per path.
        catalog: the roles tree facts.
        loop: ``auto`` or empty derives the loop from the diff, else one of
            :data:`LOOPS`.
        disable: the operator's provider keys, as :func:`resolve_disable`
            reads them.
        timings: a deploy log or role-runtimes CSV that prices the rows;
            empty prices them by declared storage.
    """
    code = {r for c in changes if c.effect == SEED for r in c.roles}
    docs = {r for c in changes if c.effect == DOC_SEED for r in c.roles} - code
    tokens, refused = catalog.affected(code)
    fulls = [f"{c.path}: {c.reason}" for c in changes if c.effect == FULL]
    full_reason = "; ".join(fulls) or refused
    full = bool(full_reason)
    seeds = sorted(code | docs)
    deploy_paths = sorted(c.path for c in changes if c.effect in (SEED, DOC_SEED, FULL))
    whitelist_tokens = sorted({*tokens, *docs})
    t3_roles = set(catalog.roles) if full else token_roles(whitelist_tokens)
    baseline, baseline_reason = _baseline(paths, catalog)

    cuts: list[dict] = []
    left_out = sorted(baseline - t3_roles)
    if left_out:
        cuts.append(
            {
                "tier": "all",
                "roles": left_out,
                "paths": {c.path: c.reason for c in changes if _narrows(c)},
                "reason": f"{baseline_reason}; the classifier narrowed these paths",
            }
        )
    disabled, kept = resolve_disable(disable, set(seeds), catalog)
    chosen = choose_loop(
        loop, changes, seeds, catalog, deploy_paths=deploy_paths, full=full
    )
    t1, t1_cuts = tiers.inner(
        changes,
        catalog,
        loop=chosen,
        disable=disabled,
        deploy_paths=deploy_paths,
        full=full,
    )
    t2, t2_cuts = tiers.presubmit(seeds, catalog, disable=disabled, full=full)
    rows = t1 + t2
    local = {row["app"] for row in rows if "app" in row} | {
        app for row in rows for app in row.get("apps", ())
    }
    beyond = sorted(t3_roles - local - set(seeds))
    if beyond:
        cuts.append(
            {
                "tier": "local",
                "roles": beyond,
                "reason": "no T1 or T2 row deploys them as its app; T3 covers them",
            }
        )
    providers = sorted({catalog.provider(key) for key in disabled} - {""})
    if providers and rows:
        cuts.append(
            {
                "tier": "local",
                "roles": providers,
                "reason": f"rendered disabled in T1 and T2 (disable={','.join(disabled)})"
                "; T3 deploys them with the seeds",
            }
        )
    t0 = unit_tier(changes, seeds, catalog)
    cuts.append({"tier": "T0", "roles": [], "reason": SUITE_CUT})
    unchecked = {
        c.path: c.reason
        for c in changes
        if c.kind != DOCS and c.effect == NONE and not c.format_only
    }
    if unchecked:
        cuts.append(
            {"tier": "T0", "roles": [], "paths": unchecked, "reason": UNCHECKED_CUT}
        )
    if t0["external"]:
        cuts.append(
            {
                "tier": "T0",
                "roles": [],
                "paths": dict.fromkeys(t0["external"], "opt-in live test"),
                "reason": EXTERNAL_CUT,
            }
        )
    cuts = tiers.merge_cuts([*cuts, *t1_cuts, *t2_cuts])
    for index, row in enumerate(rows, start=1):
        row["id"] = f"{row['tier']}-{index}"
    budgets = price(rows, catalog, disable=disabled, timings=timings)
    first = next((r for r in t1 if r.get("mode") == tiers.COMPOSE), None)
    return {
        "loop": chosen,
        "mode": first["deploy"] if first else "",
        "variant": {
            app: sorted({v for r in rows if r.get("app") == app for v in r["variants"]})
            for app in sorted({r["app"] for r in rows if "app" in r})
        },
        "network": {
            f"{r['app']}#{r['variants'][0]}": r["network"]
            for r in rows
            if r.get("mode") == tiers.SWARM
        },
        "disable": disabled,
        "kept": kept,
        "full": full_reason,
        "seeds": seeds,
        "roles": sorted(baseline | t3_roles),
        "baseline": {"roles": sorted(baseline), "reason": baseline_reason},
        "changed": [c._asdict() for c in changes],
        "tiers": {
            "T0": t0,
            "T1": [r["id"] for r in t1],
            "T2": {"rows": [r["id"] for r in t2], "gates": ["make test"]},
            "T3": {
                "whitelist": ALL if full else " ".join(whitelist_tokens),
                "roles": len(t3_roles),
                "push_widens": not full and baseline == set(catalog.roles),
            },
        },
        "rows": rows,
        "footprint": budgets["footprint"],
        "cost": budgets["cost"],
        "cuts": cuts,
    }
