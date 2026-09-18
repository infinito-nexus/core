from utils.update.base import version_depth

DIGEST_PREFIX = "sha256:"

SEMVER = "semver"
DIGEST = "digest"
REF = "ref"

RULE_BY_CLASS = {
    DIGEST: "docker-digest",
    REF: "docker-version",
}


def is_digest(version: str) -> bool:
    """Whether ``version`` pins by content rather than by name.

    Args:
        version: the ``version:`` value a role declares for an image.
    """
    return str(version).strip().startswith(DIGEST_PREFIX)


def pin_class(version: str) -> str:
    """Classify a pin as ``semver``, ``digest`` or ``ref``.

    Args:
        version: the ``version:`` value a role declares for an image.

    Returns:
        The class name. ``ref`` is the residue: a tag that names no version
        the registry can order, so nothing can tell whether it moved.
    """
    stripped = str(version).strip()
    if is_digest(stripped):
        return DIGEST
    if version_depth(stripped) > 0:
        return SEMVER
    return REF


def reference_separator(version: str) -> str:
    """The character that joins an image name to ``version`` in a pull ref.

    Args:
        version: the ``version:`` value a role declares for an image.
    """
    return "@" if is_digest(version) else ":"


def pull_reference(name: str, version: str) -> str:
    """Join an image name and a pin into the reference a registry accepts.

    Args:
        name: image name, with or without a registry prefix.
        version: the ``version:`` value a role declares for an image.
    """
    return f"{name}{reference_separator(version)}{str(version).strip()}"
