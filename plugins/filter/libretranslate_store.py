from __future__ import annotations

import posixpath

from utils.cache.artefacts import GITHUB, TREE

MINISBD_ROOT = f"{TREE}/{GITHUB}/LibreTranslate/MiniSBD/"
FROM_SOURCE = "from_source"
SOURCE = "en"
PACKAGE_PREFIX = "translate-"
MODEL_CODES = {"zh-hans": "zh", "zh-hant": "zt", "pt-br": "pb"}
PACKAGES = (".local", "share", "argos-translate", "packages")
MIN_PACKAGES = 2
SELECTION_KEYS = ("directions", "load_only", "model_store")
ENGINE = "svc-ai-libretranslate-engine"


def _kinds(records: list[dict]) -> tuple[list[dict], list[dict]]:
    argos = [record for record in records if record.get("unpack")]
    minisbd = [
        record
        for record in records
        if str(record.get("root", "")).startswith(MINISBD_ROOT)
    ]
    return argos, minisbd


def _pair(record: dict) -> tuple[str, str]:
    name = posixpath.basename(str(record["upstream"]))
    stem, dash, _ = name.rpartition("-")
    source, _, target = stem.removeprefix(PACKAGE_PREFIX).partition("_")
    if not (dash and stem.startswith(PACKAGE_PREFIX) and source and target):
        raise ValueError(
            f"{record['name']}: {name} is no "
            f"{PACKAGE_PREFIX}<source>_<target>-<version> package"
        )
    return source, target


def _model_codes(load_only: str) -> set[str]:
    codes = (code.strip().lower() for code in load_only.split(","))
    return {MODEL_CODES.get(code, code) for code in codes if code}


def _selection(
    records: list[dict], directions: str, load_only: str, enabled: bool
) -> tuple[list[dict], list[dict]]:
    if not enabled:
        return [], []
    argos, minisbd = _kinds(records)
    keep = _model_codes(load_only)
    chosen = [
        record
        for record in argos
        if (not keep or set(_pair(record)) <= keep)
        and (directions != FROM_SOURCE or _pair(record)[0] == SOURCE)
    ]
    pairs = {_pair(record) for record in chosen}
    served = {code for pair in pairs for code in pair}
    covered = (
        len(pairs) >= MIN_PACKAGES
        and keep <= served
        and (
            directions == FROM_SOURCE
            or all((target, source) in pairs for source, target in pairs)
        )
    )
    return (chosen, minisbd) if covered and minisbd else ([], [])


def libretranslate_stored(
    records: list[dict], directions: str, load_only: str, enabled: bool
) -> bool:
    """
    Args:
        records: the cache_artefacts records of svc-ai-libretranslate-engine.
        directions: the role's ``directions``; ``from_source`` selects only the
            pairs out of ``en``, ``both`` needs every selected pair pinned in
            reverse as well.
        load_only: the role's ``load_only`` joined by commas, as LT_LOAD_ONLY
            takes it; empty selects every pinned pair, otherwise only the
            pairs between the listed codes, each of which must be served.
        enabled: the role's ``model_store`` switch; false keeps the store off.

    Returns:
        True once the switch is on, the pinned Argos packages cover the
        selection in *directions* with at least MIN_PACKAGES packages, below
        which LibreTranslate fetches the package index and installs on every
        start, and the MiniSBD models are pinned.
    """
    argos, _ = _selection(records, directions, load_only, enabled)
    return bool(argos)


def libretranslate_store(
    records: list[dict],
    store: str,
    home: str,
    directions: str,
    load_only: str,
    enabled: bool,
) -> dict:
    """
    Args:
        records: the cache_artefacts records of svc-ai-libretranslate-engine.
        store: AI_MODELS_STORE_PATH, mounted at the same path in the container
            so the MiniSBD links resolve.
        home: the home directory of the container user.
        directions: as `libretranslate_stored` takes it.
        load_only: as `libretranslate_stored` takes it.
        enabled: as `libretranslate_stored` takes it.

    Returns:
        ``stored`` as `libretranslate_stored` answers it; when true,
        ``artefacts`` are the selected Argos packages and every MiniSBD model,
        the records to seed and require, ``packages`` is the ARGOS_PACKAGES_DIR
        that holds only the selected packages, one read-only bind each,
        ``minisbd`` the MiniSBD cache directory, and ``mounts`` every bind,
        all read-only; when false they are empty.
    """
    argos, minisbd = _selection(records, directions, load_only, enabled)
    if not argos:
        return {
            "stored": False,
            "artefacts": [],
            "packages": "",
            "minisbd": "",
            "mounts": [],
        }
    packages = posixpath.join(home, *PACKAGES)
    cache = posixpath.join(home, ".cache", "minisbd")
    return {
        "stored": True,
        "artefacts": [*argos, *minisbd],
        "packages": packages,
        "minisbd": cache,
        "mounts": [
            f"{store}:{store}:ro",
            f"{posixpath.join(store, minisbd[0]['root'])}:{cache}:ro",
            *(
                f"{posixpath.join(store, record['unpack'])}:"
                f"{posixpath.join(packages, record['name'])}:ro"
                for record in argos
            ),
        ],
    }


def libretranslate_selection(records: list[dict], service: dict) -> list[dict]:
    """
    Args:
        records: cache_artefacts records of any roles; only those of ENGINE
            count, the records every consumer's vars hand
            `libretranslate_store`.
        service: the configuration of a LibreTranslate consumer's service,
            which declares every key of SELECTION_KEYS; its role's vars hand
            them to `libretranslate_store` as *directions*, *load_only*
            joined by commas, and *enabled*.

    Returns:
        The Argos packages and MiniSBD models the consumer seeds as its
        selection, the ``artefacts`` `libretranslate_store` answers for it.

    Raises:
        TypeError: ``model_store`` is no boolean or ``load_only`` no list,
            which only the role's ``| bool`` and ``| join`` could read.
        ValueError: an Argos record names no package pair.
    """
    enabled, load_only = service["model_store"], service["load_only"]
    if not isinstance(enabled, bool):
        raise TypeError(f"model_store {enabled!r} is no boolean")
    if not isinstance(load_only, list):
        raise TypeError(f"load_only {load_only!r} is no list")
    argos, minisbd = _selection(
        [record for record in records if record.get("role") == ENGINE],
        str(service["directions"]),
        ",".join(str(code) for code in load_only),
        enabled,
    )
    return [*argos, *minisbd]


def libretranslate_unselected(records: list[dict]) -> list[dict]:
    """
    Args:
        records: cache_artefacts records of any roles.

    Returns:
        *records* without the Argos packages and MiniSBD models, which each
        LibreTranslate consumer seeds as the selection `libretranslate_store`
        makes for it.
    """
    argos, minisbd = _kinds(records)
    selected = {record["name"] for record in (*argos, *minisbd)}
    return [record for record in records if record["name"] not in selected]


class FilterModule:
    def filters(self):
        return {
            "libretranslate_stored": libretranslate_stored,
            "libretranslate_store": libretranslate_store,
            "libretranslate_unselected": libretranslate_unselected,
        }
