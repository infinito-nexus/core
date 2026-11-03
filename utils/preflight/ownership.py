"""Check that the docker containers and volumes a deploy declares belong to
the entity of the role that declares them: labelled with it as compose
project, or as stack namespace in swarm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

STACK_LABEL = "com.docker.stack.namespace"


def parse_labelled(output: str) -> list[tuple[str, str, str]]:
    """Split a ``<names>\\t<compose project>\\t<stack namespace>`` listing.

    Args:
        output: one line per docker object, as ``container ps --all`` or
            ``container volume ls`` print it with that ``--format``. A
            container with several names lists them comma separated.

    Returns:
        One ``(name, compose project, stack namespace)`` per name; an absent
        label is ``""``.

    Raises:
        ValueError: a line does not hold exactly three tab-separated fields.
    """
    objects: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError(f"expected <names>\\t<project>\\t<namespace>: {line!r}")
        names, project, namespace = (field.strip() for field in fields)
        objects.extend(
            (name, project, namespace) for name in names.split(",") if name.strip()
        )
    return objects


def labelled_ownership_errors(
    kind: str,
    objects: Iterable[tuple[str, str, str]],
    declared: Mapping[str, Iterable[tuple[str, str]]],
) -> list[str]:
    """Every declared object on the host that does not carry its entity's label.

    Args:
        kind: ``container`` or ``volume``, for the messages.
        objects: ``(name, compose project, stack namespace)`` of every object
            on the host, as :func:`parse_labelled` returns them.
        declared: object name -> every ``(role id, entity)`` of the roles the
            host deploys that declare an object of that name. The object
            passes when either label names any of these entities.

    Returns:
        One message per declared object whose labels name none of its
        declaring entities; a container without labels fails, a volume
        without any label passes, since compose adopts it; objects no role
        declares pass.
    """
    errors: list[str] = []
    for name, project, namespace in objects:
        claims = sorted(set(declared.get(name, ())))
        if not claims:
            continue
        if kind == "volume" and not project and not namespace:
            continue
        if {project, namespace} & {entity for _, entity in claims} - {""}:
            continue
        owners = " or ".join(f"{role} (entity '{entity}')" for role, entity in claims)
        held = " and ".join(
            label
            for label in (
                f"compose project '{project}'" if project else "",
                f"stack '{namespace}'" if namespace else "",
            )
            if label
        )
        errors.append(
            f"{kind} '{name}' belongs to {held or 'no compose project or stack'}, "
            f"but it is the {kind} of {owners}"
        )
    return errors
