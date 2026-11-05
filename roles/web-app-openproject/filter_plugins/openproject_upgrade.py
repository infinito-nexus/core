import re

from ansible.errors import AnsibleFilterError

AGGREGATED_MIGRATION = re.compile(r"^1000(\d{3})$")
LEADING_MAJOR = re.compile(r"^(\d+)")
SQUASH_FLOOR_MAJOR = 15
SQUASH_FLOOR_MIGRATION = "20241015081341"


def openproject_schema_stage(versions):
    """Return the OpenProject major that last migrated a schema.

    Every major from 16 on writes the aggregated migration ``1000NNN`` that
    squashes major NNN, and refuses a schema that holds only part of it.
    16 accepts 15.0.0 and later, whose newest squashed migration is
    ``SQUASH_FLOOR_MIGRATION``.

    Args:
        versions: the ``version`` column of ``schema_migrations``.

    Returns:
        ``None`` for an empty schema, NNN + 1 for the newest ``1000NNN``,
        ``SQUASH_FLOOR_MAJOR`` when only the floor migration is present,
        and ``SQUASH_FLOOR_MAJOR - 1`` for any older schema.
    """
    present = {str(version).strip() for version in versions} - {""}
    if not present:
        return None
    majors = [
        int(match.group(1)) + 1
        for match in map(AGGREGATED_MIGRATION.match, present)
        if match
    ]
    if majors:
        return max(majors)
    if SQUASH_FLOOR_MIGRATION in present:
        return SQUASH_FLOOR_MAJOR
    return SQUASH_FLOOR_MAJOR - 1


def openproject_upgrade_steps(versions, pinned_version):
    """Return the majors a schema must pass through before the pinned one.

    Args:
        versions: the ``version`` column of ``schema_migrations``.
        pinned_version: the pinned image tag, e.g. ``17`` or ``17.9.2``.

    Returns:
        Every major strictly between the schema stage and the pinned major,
        ascending. Empty for an empty schema or one a major away at most.

    Raises:
        AnsibleFilterError: the tag has no leading major, or the schema was
            migrated by a newer major than the pinned one.
    """
    match = LEADING_MAJOR.match(str(pinned_version).strip())
    if not match:
        raise AnsibleFilterError(
            f"openproject_upgrade_steps: image tag {pinned_version!r} names no major"
        )
    pinned = int(match.group(1))
    stage = openproject_schema_stage(versions)
    if stage is None:
        return []
    if stage > pinned:
        raise AnsibleFilterError(
            f"openproject_upgrade_steps: the database was migrated by OpenProject "
            f"major {stage}, the pinned image is major {pinned}; OpenProject "
            f"cannot migrate a schema down"
        )
    return list(range(stage + 1, pinned))


class FilterModule:
    def filters(self):
        return {
            "openproject_schema_stage": openproject_schema_stage,
            "openproject_upgrade_steps": openproject_upgrade_steps,
        }
