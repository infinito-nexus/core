"""Deploy-shape helpers shared by the complexity matrix and the Cosmos builder.

Both need the same facts about a role: whether it ships its own container
stack, and which deploy modes it supports. Keeping the logic here means the two
callers never drift.
"""

from __future__ import annotations

from pathlib import Path

from utils.roles.meta_lookup import get_role_declared_modes, get_role_mode_enabled


def role_has_stack(role_dir: Path) -> bool:
    """True iff the role renders its own container stack, i.e. ships a
    ``templates/*compose*.yml.j2``. Host-only roles (backup cron, wireguard,
    swapfile) and pure service-injectors carry no compose template and return
    False. Presence (not an ``image`` key) is the signal so build-from-source
    stacks that pull no registry image still count as a stack."""
    templates = Path(role_dir) / "templates"
    return templates.is_dir() and any(templates.rglob("*compose*.yml.j2"))


def role_deploy_modes(role_dir: Path, role_name: str | None = None) -> dict[str, bool]:
    """Return the deploy modes a role supports, keyed by mode with its
    ``modes.<mode>.enabled`` SPOT value.

    What the role declares wins. A role that names its modes gets exactly
    those, which is how an injector without a stack of its own can still be
    deployed into compose and swarm alongside the partner that carries one.

    Only a role that declares nothing falls back on its shape: a stack role
    (ships a compose template) is offered ``compose`` and ``swarm``, anything
    else is offered ``host``.
    """
    role_dir = Path(role_dir)
    modes = get_role_declared_modes(role_dir, role_name=role_name) or (
        ("compose", "swarm") if role_has_stack(role_dir) else ("host",)
    )
    return {
        mode: get_role_mode_enabled(role_dir, mode=mode, role_name=role_name)
        for mode in modes
    }
