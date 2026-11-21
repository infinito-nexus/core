"""Version pins of one release source file, read from its text.

Every reader returns ``{key: version}``; the key names the pin inside its file,
so the same reader applied to the file at two refs yields comparable mappings.
A value that still carries Jinja is no pin, it resolves elsewhere.
"""

from __future__ import annotations

import re
import tomllib

from utils.cache.yaml import load_yaml_str

PIN_KEYS = frozenset({"version", "ref", "tag"})
PIN_SUFFIXES = ("_version", "_ref")
VERSIONISH = re.compile(r"^v?\d+(?:\.\d+)+")
_URL = re.compile(r"https?://[^\s\"'<>]+")
_URL_VERSION = re.compile(r"(?<=[/@-])v?\d+(?:\.\d+)+")
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SPECIFIER = re.compile(r"(?:===|==|~=|>=)\s*([0-9][^\s,;]*)")
_PACKAGE_PIN = re.compile(r"(?<![\w.-])([A-Za-z][\w.-]*)==([0-9][\w.+-]*)")
_FROM = re.compile(
    r"^FROM\s+(?:--platform=\S+\s+)?([^\s:@$]+):([^\s$]+)", re.IGNORECASE
)
_ARG = re.compile(
    r"^(?:ARG|ENV)\s+([A-Z0-9_]*(?:VERSION|_REF|_TAG))=(\S+)", re.IGNORECASE
)


def _literal(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value)
    return None if "{{" in text or "$" in text else text


def url_version(text: str) -> str | None:
    """Return the first version inside the first URL of ``text``.

    Args:
        text: Any text; only an ``http(s)`` URL in it is searched.
    """
    url = _URL.search(text)
    match = _URL_VERSION.search(url.group()) if url else None
    return match.group() if match else None


def _url_key(url: str, version: str) -> str:
    return url.replace(version, "*").replace(version.lstrip("v"), "*")


def _walk(node: object, path: tuple[str, ...], found: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            name = str(key)
            literal = _literal(value)
            if literal and (name in PIN_KEYS or name.endswith(PIN_SUFFIXES)):
                found[".".join((*path, name))] = literal
            elif literal and (version := url_version(literal)):
                found[".".join((*path, name, "url"))] = version
            else:
                _walk(value, (*path, name), found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            label = value.get("name") if isinstance(value, dict) else None
            _walk(value, (*path, str(label or index)), found)


def meta_pins(text: str) -> dict[str, str]:
    """Read the pins of a role ``meta/`` YAML file.

    A key named ``version``, ``ref`` or ``tag``, or ending in ``_version`` or
    ``_ref``, is a pin; any other string holding a URL with a version pins
    that version under ``<path>.url``. List items are addressed by their
    ``name``, else by their index.

    Args:
        text: The YAML text.
    """
    found: dict[str, str] = {}
    _walk(load_yaml_str(text), (), found)
    return found


def collection_pins(text: str) -> dict[str, str]:
    """Read the Ansible collection pins of a ``requirements`` YAML file.

    Args:
        text: The YAML text with a ``collections`` list.
    """
    data = load_yaml_str(text) or {}
    return {
        str(item["name"]): literal
        for item in data.get("collections") or []
        if isinstance(item, dict)
        and "name" in item
        and (literal := _literal(item.get("version")))
    }


def _requirement_pin(requirement: str) -> tuple[str, str] | None:
    name = _REQUIREMENT.match(requirement)
    version = _SPECIFIER.search(requirement)
    pinned = version.group(1) if version else url_version(requirement)
    return (name.group(1).lower(), pinned) if name and pinned else None


def pyproject_pins(text: str) -> dict[str, str]:
    """Read the dependency pins of a ``pyproject.toml``.

    ``==``, ``===``, ``~=`` and ``>=`` pin their version; a direct URL
    reference pins the version inside its URL. The project's own version is
    the release itself, not a pin.

    Args:
        text: The TOML text.
    """
    data = tomllib.loads(text)
    project = data.get("project", {})
    requirements = [
        *data.get("build-system", {}).get("requires", []),
        *project.get("dependencies", []),
        *(
            item
            for extra in project.get("optional-dependencies", {}).values()
            for item in extra
        ),
    ]
    return dict(pin for item in requirements if (pin := _requirement_pin(item)))


def dockerfile_pins(text: str) -> dict[str, str]:
    """Read the literal pins of a Dockerfile.

    A ``FROM image:tag``, an ``ARG`` or ``ENV`` named ``*VERSION``, ``*_REF``
    or ``*_TAG`` with a literal value, a ``package==version`` token and a
    version inside a URL each pin; a value built from ``$`` arguments
    resolves in the role's meta files instead.

    Args:
        text: The Dockerfile text.
    """
    found: dict[str, str] = {}
    for line in text.replace("\\\n", " ").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if (match := _FROM.match(stripped)) or (match := _ARG.match(stripped)):
            found[match.group(1)] = match.group(2)
        found.update(_PACKAGE_PIN.findall(stripped))
        for url in _URL.findall(stripped):
            if (version := url_version(url)) and "$" not in url:
                found[_url_key(url, version)] = version
    return found


def _owner(key: str) -> str:
    return key.split(".", 1)[0]


def compare(
    old: dict[str, str], new: dict[str, str]
) -> list[tuple[str, str | None, str | None, str]]:
    """Return the changed, renamed and added pins between two readings of
    one file that existed at both refs.

    A key in both readings with another value changed. A versioned key that
    left and one that came under the same owner (the key's first segment),
    one each, is a renamed pin; any other versioned key that came is an
    added pin with no old value. A pin that only left is no jump.

    Args:
        old: The reading at the base ref.
        new: The reading at the target ref.

    Returns:
        ``(key, old key of a renamed pin or None, old value or None, new
        value)`` sorted by key.
    """
    rows: list[tuple[str, str | None, str | None, str]] = [
        (key, None, old[key], new[key])
        for key in old.keys() & new.keys()
        if old[key] != new[key]
    ]
    gone = [key for key in old.keys() - new.keys() if VERSIONISH.match(old[key])]
    came = [key for key in new.keys() - old.keys() if VERSIONISH.match(new[key])]
    for key in came:
        left = [g for g in gone if _owner(g) == _owner(key)]
        joined = [c for c in came if _owner(c) == _owner(key)]
        was = left[0] if len(left) == 1 and len(joined) == 1 else None
        if was is None or old[was] != new[key]:
            rows.append((key, was, old[was] if was else None, new[key]))
    return sorted(rows, key=lambda row: row[0])
