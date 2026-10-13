"""Render every integration the repository declares between two of its roles.

A role reaches an infinito-native provider through a top-level key in its
``meta/services.yml`` and an upstream provider through a ``bridges:`` entry in
one of its ``meta/addons/*.yml``. Both sides are read from the roles here, and
the axis comes from :func:`utils.roles.order.find_roles`, so a new role, a new
service key or a new add-on reaches the page on the next build.

A declared edge is not a live one. A target whose primary entity carries
``lifecycle: eol`` is marked, because the integration stays in the tree while
its flag is held at a literal ``false``; without the mark the page advertises a
partner no deployment can reach. The policy is
``docs/contributing/design/role/services/lifecycle.md``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from utils.cache.yaml import load_yaml

try:
    from utils.roles.entity.name import entity_name
except ImportError:
    from utils.roles.entity.name import get_entity_name as entity_name

from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_lifecycle
from utils.roles.order import find_roles

AXIS_PREFIXES = ["web-app-", "web-svc-"]
GROUP_MEMBER = re.compile(r"'([a-z0-9-]+)' in group_names")
EOL = "eol"
EOL_MARK = " (end of life)"

EOL_NOTE = """\
A target marked ``(end of life)`` is a role the project no longer maintains or
tests. The integration stays declared, but the partner's service flag is a
literal ``false`` no inventory turns on, so the edge is dormant.

"""

OVERVIEW_HEADER = (
    """\
Integrations
============

Every integration this repository declares between two of its own roles. A
role names its provider as a key in ``meta/services.yml``, and an add-on under
``meta/addons/`` names the same key in its ``bridges:`` list. Both sides are
read from the roles on each build, so this page cannot fall behind them.

"""
    + EOL_NOTE
)

SERVICES_HEADER = (
    """\
Native Integrations
===================

The provider each role wires itself into through ``meta/services.yml``, listed
under the service key that declares the link.

"""
    + EOL_NOTE
)

ADDONS_HEADER = (
    """\
Add-On Integrations
===================

The add-on each role installs to reach another role, listed with the service
key it bridges and the role that key resolves to.

"""
    + EOL_NOTE
)


def axis(roles_dir: Path) -> list[str]:
    """Return every role the matrix covers, in name order.

    Args:
        roles_dir: directory holding the role folders.
    """
    return [path.name for path, _ in find_roles(roles_dir, AXIS_PREFIXES)]


def _gated_roles(entry) -> set[str]:
    """Return every role name a ``meta/services.yml`` entry gates itself on.

    Args:
        entry: the value of one top-level service key.
    """
    return set(GROUP_MEMBER.findall(str(entry)))


def _services(role_path: Path) -> dict:
    """Return the ``meta/services.yml`` of a role, empty when it has none.

    Args:
        role_path: the role directory.
    """
    return load_yaml(str(role_path / ROLE_FILE_META_SERVICES), default_if_missing={})


def service_targets(roles_dir: Path, roles: list[str]) -> dict[str, str]:
    """Return the role each service key reaches, keyed by service key.

    A key resolves to the role whose group membership its entry gates itself
    on, and otherwise to the role carrying it as an entity name. A key that
    resolves to neither names no role on the axis and is absent from the
    result.

    Args:
        roles_dir: directory holding the role folders.
        roles: the role names on the axis.
    """
    targets = {entity_name(role): role for role in roles}
    on_axis = set(roles)
    for role in roles:
        for key, entry in _services(Path(roles_dir) / role).items():
            gated = _gated_roles(entry) & on_axis
            if len(gated) == 1:
                targets[key] = gated.pop()
    return targets


def eol_roles(roles_dir: Path, roles: list[str]) -> set[str]:
    """Return the roles on the axis whose primary entity is ``lifecycle: eol``.

    Args:
        roles_dir: directory holding the role folders.
        roles: the role names on the axis.
    """
    return {
        role
        for role in roles
        if get_role_lifecycle(Path(roles_dir) / role, role_name=role) == EOL
    }


def render_target(role: str, eol: set[str]) -> str:
    """Return one target role, marked when the partner is end of life.

    Args:
        role: the target role name.
        eol: the role names :func:`eol_roles` reported.
    """
    return f"``{role}``{EOL_MARK if role in eol else ''}"


def service_edges(role_path: Path, targets: dict[str, str]) -> list[tuple[str, str]]:
    """Return ``(service key, role)`` for every native integration of a role.

    Args:
        role_path: the role directory.
        targets: the role each service key reaches.
    """
    return sorted(
        (key, targets[key])
        for key in _services(role_path)
        if key in targets and targets[key] != role_path.name
    )


def addon_edges(role_path: Path, targets: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return ``(add-on, service key, role)`` for every bridge a role declares.

    Args:
        role_path: the role directory.
        targets: the role each service key reaches.
    """
    return sorted(
        (addon.stem, key, targets[key])
        for addon in (role_path / ROLE_DIR_META_ADDONS).glob("*.yml")
        for key in load_yaml(str(addon)).get("bridges") or []
        if key in targets and targets[key] != role_path.name
    )


def _block(role: str, items: list[str]) -> str:
    """Return one definition-list entry for a role.

    Args:
        role: the role name.
        items: body lines, rendered as a bullet list.
    """
    if not items:
        return f"``{role}``\n   None."
    return "\n".join([f"``{role}``", *(f"   * {item}" for item in items)])


def generate(roles_dir: Path, output_dir: Path) -> int:
    """Write the integration pages.

    Args:
        roles_dir: directory holding the role folders.
        output_dir: directory the ``.rst`` pages are written to.

    Returns:
        How many roles the pages cover.
    """
    roles = axis(roles_dir)
    targets = service_targets(roles_dir, roles)
    eol = eol_roles(roles_dir, roles)
    overview, services, addons = [], [], []
    for role in roles:
        native = service_edges(Path(roles_dir) / role, targets)
        bridged = addon_edges(Path(roles_dir) / role, targets)
        reached = sorted(
            {target for _, target in native} | {target for _, _, target in bridged}
        )
        overview.append(_block(role, [render_target(t, eol) for t in reached]))
        services.append(
            _block(
                role,
                [
                    f"``{key}`` -> {render_target(target, eol)}"
                    for key, target in native
                ],
            )
        )
        addons.append(
            _block(
                role,
                [
                    f"``{addon}``: ``{key}`` -> {render_target(target, eol)}"
                    for addon, key, target in bridged
                ],
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, header, blocks in (
        ("overview", OVERVIEW_HEADER, overview),
        ("services", SERVICES_HEADER, services),
        ("addons", ADDONS_HEADER, addons),
    ):
        (output_dir / f"{name}.rst").write_text(
            header + "\n\n".join(blocks) + "\n", encoding="utf-8"
        )
    return len(roles)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate the integration matrix from the roles."
    )
    parser.add_argument("--roles-dir", required=True, help="Directory of the roles.")
    parser.add_argument("--output-dir", required=True, help="Directory for the pages.")
    args = parser.parse_args(argv)

    output = Path(args.output_dir)
    count = generate(Path(args.roles_dir), output)
    print(f"{count} role(s) written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
