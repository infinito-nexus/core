from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ansible.errors import AnsibleFilterError

from utils.cache.artefacts import pin_problems, records

BLOB_PREFIX = "sha256-"
DECLARATIONS = "AI_LOCAL_MODEL_DECLARATIONS"
PIN_KEYS = ("url", "revision", "sha256", "bytes")
OLLAMA_VERSION = "0.40.16"
NAMED = {
    "renderer": frozenset({"gemma4", "qwen3-coder"}),
    "parser": frozenset({"gemma4", "qwen3-coder"}),
}
PARAMETERS = frozenset(
    {
        "min_p",
        "num_predict",
        "repeat_last_n",
        "repeat_penalty",
        "seed",
        "stop",
        "temperature",
        "top_k",
        "top_p",
    }
)
SMALLEST = 1e-4
BOUND = 1e6


def _plain_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(value):
        return False
    if value != 0 and not SMALLEST <= abs(value) < BOUND:
        return False
    return float(f"{value:.6g}") == float(value)


def _stop_token(value) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value.isprintable()
        and not any(char.isspace() or char in '"\\' for char in value)
    )


def _parameter_problem(name, value) -> str:
    if name not in PARAMETERS:
        return f"parameter {name!r} is not one of {', '.join(sorted(PARAMETERS))}"
    if name == "stop":
        if isinstance(value, list) and value and all(map(_stop_token, value)):
            return ""
        return (
            "parameter stop is not a list of 1 to 64 printable characters "
            "without whitespace, quotes or backslashes"
        )
    if _plain_number(value):
        return ""
    return (
        f"parameter {name} {value!r} is not a number of at most 6 significant "
        f"digits, zero or between {SMALLEST:g} and {BOUND:g} in magnitude"
    )


def _directive_problems(entry: Mapping) -> list[str]:
    found = [
        f"{key} {entry[key]!r} is not one of {', '.join(sorted(names))}"
        for key, names in NAMED.items()
        if key in entry and (not isinstance(entry[key], str) or entry[key] not in names)
    ]
    parameters = entry.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return [*found, "parameters is not a mapping"]
    found.extend(_parameter_problem(name, value) for name, value in parameters.items())
    return found


def _rendered(value) -> str:
    if isinstance(value, str):
        return value
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def local_model_refusal(entry) -> str:
    """Why *entry* is refused as a local model file to fetch, or ``''``.

    Args:
        entry: one ``AI_LOCAL_MODELS`` or ``preload_models`` declaration.
    """
    if not isinstance(entry, Mapping):
        return f"the entry is a {type(entry).__name__}, not a mapping"
    found = pin_problems(
        str(entry.get("url") or ""),
        str(entry.get("revision") or ""),
        str(entry.get("sha256") or ""),
        str(entry.get("bytes") or ""),
    ) + _directive_problems(entry)
    return "; ".join(problem for problem in found if problem)


def local_model_directives(entry: Mapping) -> list[str]:
    """
    Args:
        entry: a declaration ``local_model_refusal`` accepts.

    Returns:
        Its ``RENDERER``, ``PARSER`` and ``PARAMETER`` lines, each as
        ``ollama show --modelfile`` prints it back.
    """
    lines = [f"{key.upper()} {entry[key]}" for key in NAMED if key in entry]
    for name, value in sorted((entry.get("parameters") or {}).items()):
        values = value if name == "stop" else [value]
        lines.extend(f"PARAMETER {name} {_rendered(item)}" for item in values)
    return lines


def local_model_modelfile(entry, source: str) -> str:
    """
    Args:
        entry: the declaration to create the model of.
        source: the path of its pinned file inside the Ollama container.

    Returns:
        The Modelfile: ``FROM`` the file, then the entry's directives.

    Raises:
        AnsibleFilterError: ``local_model_refusal`` refuses the entry.
    """
    refusal = local_model_refusal(entry)
    if refusal:
        raise AnsibleFilterError(f"local_model_modelfile: {refusal}")
    return "\n".join([f"FROM {source}", *local_model_directives(entry)]) + "\n"


def _held(model: Mapping, shown: str) -> bool:
    lines = set(shown.splitlines())
    return BLOB_PREFIX + str(model["sha256"]) in shown and all(
        line in lines for line in local_model_directives(model)
    )


def local_models_missing(results: Iterable[Mapping]) -> list[dict]:
    """Every model whose ``ollama show --modelfile`` output lacks its file's blob or a directive.

    Args:
        results: registered loop results, each with the ``model`` it read and
            the ``stdout`` of that read.
    """
    return [
        dict(result["model"])
        for result in results or []
        if not _held(result["model"], str(result.get("stdout") or ""))
    ]


def local_models_pinned(declarations, artefacts: Mapping) -> list[dict]:
    """
    Args:
        declarations: the ``AI_LOCAL_MODEL_DECLARATIONS`` entries, each naming
            its manifest entry under ``artefact``.
        artefacts: the ``cache_artefacts`` records, keyed by name.

    Returns:
        Every declaration with ``url``, ``revision``, ``sha256`` and ``bytes``
        taken from its artefact.

    Raises:
        AnsibleFilterError: a declaration names no declared artefact, or sets
            one of those keys itself and so pins the file a second time.
    """
    pinned: list[dict] = []
    for entry in declarations or []:
        alias = entry.get("alias")
        doubled = sorted(set(PIN_KEYS) & set(entry))
        if doubled:
            raise AnsibleFilterError(
                f"local_models_pinned: {alias} sets {', '.join(doubled)} itself; "
                "the manifest artefact is the one source"
            )
        artefact = artefacts.get(str(entry.get("artefact") or ""))
        if artefact is None:
            raise AnsibleFilterError(
                f"local_models_pinned: {alias} names artefact "
                f"{entry.get('artefact')!r}, which no role declares"
            )
        pinned.append({**entry, **{key: artefact[key] for key in PIN_KEYS}})
    return pinned


def declared_local_models(variables: Mapping) -> list[dict]:
    """
    Args:
        variables: the parsed ``group_vars/all/16_ai.yml``.

    Returns:
        ``AI_LOCAL_MODELS`` as a deploy resolves it, against the upstream urls.
    """
    return local_models_pinned(variables.get(DECLARATIONS) or [], records(""))


class FilterModule:
    def filters(self):
        return {
            "local_model_modelfile": local_model_modelfile,
            "local_model_refusal": local_model_refusal,
            "local_models_missing": local_models_missing,
            "local_models_pinned": local_models_pinned,
        }
