"""Which deploy row replays the role's README instructions, and in what mode.

The instructions test used to be a job of its own that picked one random role
per run. Riding along on a deploy row instead costs no extra runner and covers
every role the sweep touches. The row it rides on is the role's smallest
variant -- the one enabling the fewest services -- because that is the shape
the README's Production block describes: the bare role, with the optional
providers switched off.

The replay is a second deploy on the same runner, so the row it picks must be
one the guide can actually deploy: the README has to carry a Production block,
and the guide's own mode (``compose`` for a role that ships a stack, ``host``
for one installed onto the machine) has to be a mode the role runs and tests.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT
from utils.roles.deploy import role_has_stack
from utils.roles.meta_lookup import get_role_mode_enabled, get_role_test_skips

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from typing import Any

PRODUCTION_HEADING = "### Production"
"""The README section :file:`scripts/github/guide/compose_deploy.sh` replays.
A role without it has no instructions to test."""


def _enabled_services(variant: Mapping[str, Any]) -> int:
    services = variant.get("services") or {}
    return sum(
        1
        for config in services.values()
        if isinstance(config, dict) and config.get("enabled")
    )


def smallest_variant(
    variants: Sequence[Mapping[str, Any]], allowed: Collection[str] | None = None
) -> str:
    """The variant that enables the fewest services, as the matrix writes it;
    the lowest index wins a tie, and ``''`` means none qualifies.

    Args:
        variants: the role's rendered variant configs, in index order.
        allowed: the variants this sweep actually deploys. A variant the sweep
            cuts as redundant coverage never reaches a runner, so hanging the
            replay on it would silently drop the role from the instructions
            test; the next-smallest deployed variant carries it instead.
    """
    candidates = [
        index
        for index in range(len(variants))
        if allowed is None or str(index) in allowed
    ]
    if not candidates:
        return ""
    return str(
        min(candidates, key=lambda index: (_enabled_services(variants[index]), index))
    )


@cache
def guide_deployable(app: str) -> str:
    """The mode the guide would replay *app* in, or ``''`` when it cannot.

    Independent of the variant, and cached: the answer is a property of the
    role's files, and :func:`utils.github.variant.axes.assign` asks it once per
    row of every chunk.
    """
    role_dir = PROJECT_ROOT / "roles" / app
    readme = role_dir / "README.md"
    if not readme.is_file() or PRODUCTION_HEADING not in readme.read_text(
        encoding="utf-8"
    ):
        return ""
    mode = "compose" if role_has_stack(role_dir) else "host"
    if mode in get_role_test_skips(role_dir, role_name=app):
        return ""
    if not get_role_mode_enabled(role_dir, mode=mode, role_name=app):
        return ""
    return mode


def guide_variant(
    app: str,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    allowed: Collection[str],
) -> tuple[str, str]:
    """The variant of *app* that carries the replay, and the mode it runs in.

    ``('', '')`` when the role has no instructions to replay or this sweep
    deploys no variant that could carry them.

    Args:
        app: the role.
        variants_per_app: rendered variant configs per app; without them no
            variant can be told to be the smallest one.
        allowed: the variants this sweep deploys, as the matrix writes them.
    """
    variants = (variants_per_app or {}).get(app)
    if not variants:
        return "", ""
    mode = guide_deployable(app)
    if not mode:
        return "", ""
    variant = smallest_variant(variants, allowed)
    return (variant, mode) if variant else ("", "")
