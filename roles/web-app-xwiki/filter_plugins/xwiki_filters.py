from __future__ import annotations

import re


def xwiki_extension_status(raw: str) -> int:
    """
    Parse the output of the Groovy CheckExtension page.

    - Strips HTML tags and entities (&nbsp;)
    - Returns 200 if extension is INSTALLED, otherwise 404

    Args:
        raw: Raw HTTP body from the checker page.

    Returns:
        200 if installed, 404 if missing/unknown.
    """
    if raw is None:
        return 404

    text = re.sub(r"<[^>]+>", "", str(raw))
    text = text.replace("&nbsp;", " ").replace("\u00a0", " ")
    text = text.strip()

    if text.startswith("INSTALLED::"):
        return 200
    return 404


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def xwiki_enabled_install_items(addons: dict) -> list:
    """Build the extension installer list from the meta/addons/ map.

    Selects the enabled addons (the loader-normalised ``enabled`` value may be a
    real bool or a rendered Jinja string) and maps each to the installer's
    ``{id, version}`` shape, where the upstream Maven coordinate is carried
    under ``config.id`` and the version pin lives at the top-level ``version``.

    Args:
        addons: The resolved ``applications.web-app-xwiki.addons`` map.

    Returns:
        A list of ``{"id": <maven-coordinate>, "version": <pin>}`` dicts.
    """
    items = []
    for spec in (addons or {}).values():
        if not isinstance(spec, dict) or not _is_truthy(spec.get("enabled")):
            continue
        config = spec.get("config") or {}
        items.append(
            {
                "id": config.get("id", ""),
                "version": spec.get("version", ""),
            }
        )
    return items


class FilterModule:
    """Custom filters for XWiki helpers."""

    def filters(self):
        return {
            "xwiki_extension_status": xwiki_extension_status,
            "xwiki_enabled_install_items": xwiki_enabled_install_items,
        }
