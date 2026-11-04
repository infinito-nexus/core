from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def custom_image_name(custom, entity_name: Callable[[], str]) -> str:
    """Name of the image a service declaring ``custom`` builds locally.

    Args:
        custom: the service's truthy ``custom`` value. A non-empty string names
            the image, any other value names it after the role's entity.
        entity_name: returns the entity name of the role that builds the image,
            called only when ``custom`` names no image itself.

    Returns:
        ``<base>_custom``, or ``""`` when the base is empty.
    """
    if isinstance(custom, str) and custom.strip():
        base = custom.strip()
    else:
        base = str(entity_name()).strip()
    return f"{base}_custom" if base else ""
