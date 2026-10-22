from __future__ import annotations

import json
import re

from ansible.errors import AnsibleFilterError

_OC_VERSION = re.compile(
    r"\$OC_Version\s*=\s*(?:array\s*\(|\[)(?P<parts>[^)\]]*)(?:\)|\])\s*;"
)
_TAG = re.compile(r"^(?P<major>\d+)(?:\.\d+)*(?P<suffix>.*)$")
_INCOMPATIBLE = re.compile(r"Disabled incompatible app: (?P<app>[A-Za-z0-9_.-]+)")
_STATUS_KEYS = ("installed", "versionstring", "maintenance", "needsDbUpgrade")


def nextcloud_version_php(content):
    """Return the dotted ``$OC_Version`` a Nextcloud ``version.php`` declares.

    Args:
        content: text of ``version.php`` from the code volume.

    Returns:
        The version as ``major.minor.patch.build``, e.g. ``31.0.11.1``.
    """
    match = _OC_VERSION.search(str(content))
    if match is None:
        raise AnsibleFilterError("nextcloud_version_php: no $OC_Version in version.php")
    parts = [part.strip() for part in match.group("parts").split(",")]
    if not all(part.isdigit() for part in parts):
        raise AnsibleFilterError(
            f"nextcloud_version_php: $OC_Version is not numeric: {match.group(0)}"
        )
    return ".".join(parts)


def nextcloud_tag_major(tag):
    """Return the major version a Nextcloud image tag or version string starts with.

    Args:
        tag: image tag such as ``34-fpm-alpine`` or version such as ``34.0.5.1``.

    Returns:
        The major version as an integer.
    """
    match = _TAG.match(str(tag).strip())
    if match is None:
        raise AnsibleFilterError(
            f"nextcloud_tag_major: '{tag}' does not start with a major version"
        )
    return int(match.group("major"))


def nextcloud_major_steps(installed_version, target_tag):
    """Return the image tags that bring installed data up to the pinned major.

    Args:
        installed_version: version ``version.php`` declares, ``""`` when nothing
            is installed.
        target_tag: pinned image tag, e.g. ``34-fpm-alpine``.

    Returns:
        One tag per major above the installed one, the pinned tag last; empty
        when nothing is installed or the installed major is the pinned one.
    """
    if not str(installed_version).strip():
        return []
    installed_major = nextcloud_tag_major(installed_version)
    target_major = nextcloud_tag_major(target_tag)
    match = _TAG.match(str(target_tag).strip())
    if installed_major > target_major:
        raise AnsibleFilterError(
            f"Nextcloud data was written by {installed_version}, newer than the "
            f"pinned image tag {target_tag}; Nextcloud cannot downgrade"
        )
    if installed_major == target_major:
        return []
    intermediate = [
        f"{major}{match.group('suffix')}"
        for major in range(installed_major + 1, target_major)
    ]
    return [*intermediate, str(target_tag).strip()]


def _json_object(output, keys, name):
    for raw in reversed(str(output).splitlines()):
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and all(key in parsed for key in keys):
            return parsed
    raise AnsibleFilterError(f"{name}: no JSON object in output: {str(output)[-500:]}")


def nextcloud_disabled_apps(output, app_list):
    """Return the apps an upgrade step left disabled, sorted.

    ``occ upgrade`` disables every incompatible app and enables it again once
    the app store delivered a compatible release, so a ``Disabled incompatible
    app`` line only counts while the app is still missing from the enabled
    apps after the step. The entrypoint's own "apps have been disabled" list
    also names every app that was only updated and is not used.

    Args:
        output: stdout of the image entrypoint run with ``NEXTCLOUD_UPDATE=1``.
        app_list: stdout of ``occ app:list --output=json`` after the step.

    Returns:
        The app ids ``occ upgrade`` disabled that are not enabled afterwards.
    """
    enabled = _json_object(app_list, ("enabled",), "nextcloud_disabled_apps")["enabled"]
    disabled = {match.group("app") for match in _INCOMPATIBLE.finditer(str(output))}
    return sorted(disabled - set(enabled))


def nextcloud_status(output):
    """Return the object ``occ status --output=json`` printed.

    Args:
        output: stdout of ``occ status --output=json``; PHP notices before the
            JSON line are skipped.

    Returns:
        The status dict with at least ``installed``, ``versionstring``,
        ``maintenance`` and ``needsDbUpgrade``.
    """
    return _json_object(output, _STATUS_KEYS, "nextcloud_status")


class FilterModule:
    def filters(self):
        return {
            "nextcloud_version_php": nextcloud_version_php,
            "nextcloud_tag_major": nextcloud_tag_major,
            "nextcloud_major_steps": nextcloud_major_steps,
            "nextcloud_disabled_apps": nextcloud_disabled_apps,
            "nextcloud_status": nextcloud_status,
        }
