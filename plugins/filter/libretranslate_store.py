from __future__ import annotations

import posixpath

from utils.cache.artefacts import GITHUB, TREE

MINISBD_ROOT = f"{TREE}/{GITHUB}/LibreTranslate/MiniSBD/"


def _kinds(records: list[dict]) -> tuple[list[dict], list[dict]]:
    argos = [record for record in records if record.get("unpack")]
    minisbd = [
        record
        for record in records
        if str(record.get("root", "")).startswith(MINISBD_ROOT)
    ]
    return argos, minisbd


def libretranslate_stored(records: list[dict]) -> bool:
    """
    Args:
        records: the cache_artefacts records of svc-ai-libretranslate-engine.

    Returns:
        True once they pin both Argos packages and MiniSBD models.
    """
    argos, minisbd = _kinds(records)
    return bool(argos and minisbd)


def libretranslate_store(records: list[dict], store: str, home: str) -> dict:
    """
    Args:
        records: the cache_artefacts records of svc-ai-libretranslate-engine.
        store: AI_MODELS_STORE_PATH, mounted at the same path in the container.
        home: the home directory of the container user.

    Returns:
        ``stored`` as `libretranslate_stored` answers it; when true,
        ``packages`` is the ARGOS_PACKAGES_DIR of the unpacked packages,
        ``minisbd`` the MiniSBD cache directory and ``mounts`` both read-only;
        when false they are empty.
    """
    if not libretranslate_stored(records):
        return {"stored": False, "packages": "", "minisbd": "", "mounts": []}
    argos, minisbd = _kinds(records)
    cache = posixpath.join(home, ".cache", "minisbd")
    return {
        "stored": True,
        "packages": posixpath.join(store, posixpath.dirname(argos[0]["unpack"])),
        "minisbd": cache,
        "mounts": [
            f"{store}:{store}:ro",
            f"{posixpath.join(store, minisbd[0]['root'])}:{cache}:ro",
        ],
    }


class FilterModule:
    def filters(self):
        return {
            "libretranslate_stored": libretranslate_stored,
            "libretranslate_store": libretranslate_store,
        }
