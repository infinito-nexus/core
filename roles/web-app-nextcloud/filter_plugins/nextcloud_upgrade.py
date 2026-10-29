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
_LEADING_DIGITS = re.compile(r"[0-9]+")
_PHP_SPECIAL_FORMS = (
    ("dev", 0),
    ("alpha", 1),
    ("a", 1),
    ("beta", 2),
    ("b", 2),
    ("RC", 3),
    ("rc", 3),
    ("#", 4),
    ("pl", 5),
    ("p", 5),
)


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


def nextcloud_needs_post_upgrade(status_output, installed_version, repaired_output):
    """Return whether the running Nextcloud still owes its post-upgrade pass.

    Args:
        status_output: stdout of ``occ status --output=json`` after ``occ upgrade``.
        installed_version: version ``version.php`` declared before this deploy
            started the pinned image, ``""`` when no data was found.
        repaired_output: stdout of ``occ config:app:get files mimetype_version
            --default-value=``, the server version the expensive repair last
            ran for, empty when it never ran.

    Returns:
        True when this deploy changed the running version or the expensive
        repair has not run for it yet.
    """
    running = _json_object(
        status_output, (*_STATUS_KEYS, "version"), "nextcloud_needs_post_upgrade"
    )["version"]
    installed = str(installed_version).strip()
    lines = [line.strip() for line in str(repaired_output).splitlines() if line.strip()]
    repaired = lines[-1] if lines else ""
    return installed not in ("", running) or repaired != running


def _is_digit(char):
    return char != "" and char in "0123456789"


def _is_non_digit(char):
    return not _is_digit(char) and char != "."


def _php_canonical_version(version):
    out = [version[0]]
    last = version[0]
    for char in version[1:]:
        if char in "-_+":
            if out[-1] != ".":
                out.append(".")
        elif (_is_non_digit(last) and _is_digit(char)) or (
            _is_digit(last) and _is_non_digit(char)
        ):
            if out[-1] != ".":
                out.append(".")
            out.append(char)
        elif not (char.isascii() and char.isalnum()):
            if out[-1] != ".":
                out.append(".")
        else:
            out.append(char)
        last = char
    if out[-1] == ".":
        out.pop()
    return "".join(out)


def _php_special_form(form):
    for name, order in _PHP_SPECIAL_FORMS:
        if form.startswith(name):
            return order
    return -1


def _sign(value):
    return (value > 0) - (value < 0)


def _php_compare_parts(left, right):
    if _is_digit(left[:1]) and _is_digit(right[:1]):
        return _sign(
            int(_LEADING_DIGITS.match(left).group())
            - int(_LEADING_DIGITS.match(right).group())
        )
    if not _is_digit(left[:1]) and not _is_digit(right[:1]):
        return _sign(_php_special_form(left) - _php_special_form(right))
    if _is_digit(left[:1]):
        return _sign(_php_special_form("#N#") - _php_special_form(right))
    return _sign(_php_special_form(left) - _php_special_form("#N#"))


def _php_version_compare(left, right):
    if not left or not right:
        if not left and not right:
            return 0
        return 1 if left else -1
    rest1 = left if left[0] == "#" else _php_canonical_version(left)
    rest2 = right if right[0] == "#" else _php_canonical_version(right)
    more1 = more2 = True
    compare = 0
    while rest1 and rest2 and more1 and more2:
        part1, dot1, tail1 = rest1.partition(".")
        part2, dot2, tail2 = rest2.partition(".")
        more1, more2 = bool(dot1), bool(dot2)
        compare = _php_compare_parts(part1, part2)
        if compare != 0:
            break
        if more1:
            rest1 = tail1
        if more2:
            rest2 = tail2
    if compare == 0:
        if more1:
            compare = 1 if _is_digit(rest1[:1]) else _php_version_compare(rest1, "#N#")
        elif more2:
            compare = -1 if _is_digit(rest2[:1]) else _php_version_compare("#N#", rest2)
    return compare


def nextcloud_cached_app_updates(update_check_output, app_list_output, pinned):
    """Return the unpinned enabled apps the daily update check found a newer release for.

    Args:
        update_check_output: stdout of ``occ config:list updatenotification
            --output=json``; the update check stores the newest release it saw
            under the app id.
        app_list_output: stdout of ``occ app:list --enabled --output=json``.
        pinned: app ids whose release the role pins and never updates.

    Returns:
        Sorted app ids; empty when the update check stored nothing.
    """
    name = "nextcloud_cached_app_updates"
    enabled = _json_object(app_list_output, ("enabled",), name)["enabled"]
    stored = _json_object(update_check_output, ("apps",), name)["apps"]
    if not isinstance(enabled, dict) or not isinstance(stored, dict):
        return []
    if "updatenotification" not in stored:
        return []
    found = stored["updatenotification"]
    if not isinstance(found, dict):
        return []
    updates = []
    for app, installed in enabled.items():
        if app in pinned or app not in found:
            continue
        available = found[app]
        if not isinstance(installed, str) or not isinstance(available, str):
            continue
        if _php_version_compare(available.strip(), installed.strip()) > 0:
            updates.append(app)
    return sorted(updates)


class FilterModule:
    def filters(self):
        return {
            "nextcloud_version_php": nextcloud_version_php,
            "nextcloud_tag_major": nextcloud_tag_major,
            "nextcloud_major_steps": nextcloud_major_steps,
            "nextcloud_disabled_apps": nextcloud_disabled_apps,
            "nextcloud_status": nextcloud_status,
            "nextcloud_needs_post_upgrade": nextcloud_needs_post_upgrade,
            "nextcloud_cached_app_updates": nextcloud_cached_app_updates,
        }
