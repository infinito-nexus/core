"""What an image's config blob declares: its healthcheck and its volumes.

The manifest names a config blob and the blob carries the sections a
``Dockerfile`` baked in. Reading one section is the same walk as reading
another, so both callers share it: resolve the index to a platform, read the
blob, take the section.

Every answer is three-valued. ``{}`` means the image definitively declares
nothing, ``None`` means the walk could not finish, and a caller that reads the
two as the same thing turns an auth wall or a rate limit into evidence.
"""

from __future__ import annotations

from utils.docker.mirror import mirror_image
from utils.docker.registry import (
    cache_read,
    cache_write,
    fetch_blob,
    fetch_manifest,
    platform_digest,
    probe_order,
)


def _section_at(
    image: str, reference: str, section: str, os_name: str, architecture: str
) -> dict | None:
    doc = fetch_manifest(image, reference)
    if doc is None:
        return None
    manifests = doc.get("manifests")
    if isinstance(manifests, list) and manifests:
        digest = platform_digest(manifests, os_name, architecture)
        if digest is None:
            return None
        doc = fetch_manifest(image, digest)
        if doc is None or doc.get("manifests"):
            return None
    config_digest = (doc.get("config") or {}).get("digest")
    if not isinstance(config_digest, str) or not config_digest:
        return None
    blob = fetch_blob(image, config_digest)
    if blob is None:
        return None
    return (blob.get("config") or {}).get(section) or {}


def _section_probed(
    section: str, kind: str, image: str, reference: str, os_name: str, architecture: str
) -> tuple[dict | None, str]:
    """The named config section, and which address answered for it.

    Args:
        section: key under the blob's ``config``, e.g. ``Healthcheck``.
        kind: cache namespace, so two sections never share an entry.
        image: image name, with or without registry host.
        reference: tag or digest.
        os_name: platform to resolve a multi-arch index to.
        architecture: platform to resolve a multi-arch index to.

    Returns:
        ``(section, source)`` where source is ``cache``, ``mirror``,
        ``upstream`` or ``none``.
    """
    cached = cache_read(kind, image, reference, os_name, architecture)
    if isinstance(cached, dict):
        return cached, "cache"
    mirrored = mirror_image(image)
    for candidate in probe_order(image):
        found = _section_at(candidate, reference, section, os_name, architecture)
        if found is not None:
            cache_write(kind, found, image, reference, os_name, architecture)
            return found, "mirror" if candidate == mirrored else "upstream"
    return None, "none"


def image_healthcheck(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> dict | None:
    """Return the ``HEALTHCHECK`` baked into ``image:reference``.

    Args:
        image: image name, with or without registry host.
        reference: tag or digest.
        os_name: platform to resolve a multi-arch index to.
        architecture: platform to resolve a multi-arch index to.

    Returns:
        The image's healthcheck config, ``{}`` when the image definitively
        declares none, and ``None`` when the answer is indeterminate.

    Reads from the mirror first and falls back to the upstream registry only
    for images the mirror does not carry, so a full sweep does not spend the
    upstream's rate limit. Determinate answers are cached on disk.
    """
    return image_healthcheck_probed(
        image, reference, os_name=os_name, architecture=architecture
    )[0]


def image_healthcheck_probed(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> tuple[dict | None, str]:
    """:func:`image_healthcheck` plus which address answered.

    Returns:
        ``(healthcheck, source)``. Reading upstream is the documented fallback
        for images the mirror does not carry; a caller that sweeps many images
        can use the counts to tell a fallback from a mirror that stopped
        working.
    """
    return _section_probed(
        "Healthcheck", "healthcheck", image, reference, os_name, architecture
    )


def image_volumes(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> dict | None:
    """Return the ``VOLUME`` paths baked into ``image:reference``.

    Args:
        image: image name, with or without registry host.
        reference: tag or digest.
        os_name: platform to resolve a multi-arch index to.
        architecture: platform to resolve a multi-arch index to.

    Returns:
        A mapping whose keys are the declared container paths, ``{}`` when the
        image definitively declares none, and ``None`` when the answer is
        indeterminate.
    """
    return _section_probed(
        "Volumes", "volumes", image, reference, os_name, architecture
    )[0]
