from __future__ import annotations

from collections.abc import Iterable, Mapping

from utils.cache.artefacts import pin_problems

BLOB_PREFIX = "sha256-"


def local_model_refusal(entry) -> str:
    """Why *entry* is refused as a local model file to fetch, or ``''``.

    Args:
        entry: one ``AI_LOCAL_MODELS`` or ``preload_models`` declaration.
    """
    if not isinstance(entry, Mapping):
        return f"the entry is a {type(entry).__name__}, not a mapping"
    return "; ".join(
        pin_problems(
            str(entry.get("url") or ""),
            str(entry.get("revision") or ""),
            str(entry.get("sha256") or ""),
            str(entry.get("bytes") or ""),
        )
    )


def local_models_missing(results: Iterable[Mapping]) -> list[dict]:
    """Every model whose ``ollama show --modelfile`` output names no blob of its file.

    Args:
        results: registered loop results, each with the ``model`` it read and
            the ``stdout`` of that read.
    """
    return [
        dict(result["model"])
        for result in results or []
        if BLOB_PREFIX + str(result["model"]["sha256"])
        not in str(result.get("stdout") or "")
    ]


class FilterModule:
    def filters(self):
        return {
            "local_model_refusal": local_model_refusal,
            "local_models_missing": local_models_missing,
        }
