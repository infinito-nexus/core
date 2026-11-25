from __future__ import annotations


def lmstudio_declared_models(declared):
    """
    Args:
      declared: the declared preload models, each with repo, file, url and
        optional mirrors.

    Returns:
      One model per repo/file, compared case-sensitively, in declaration
      order: its first declaration with ``mirrors`` set to every further url
      and mirror of all its declarations, each once.
    """
    first: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}
    for model in declared:
        path = f"{model['repo']}/{model['file']}"
        first.setdefault(path, model)
        urls = sources.setdefault(path, [])
        for url in [model["url"], *(model.get("mirrors") or [])]:
            if url not in urls:
                urls.append(url)
    return [{**first[path], "mirrors": urls[1:]} for path, urls in sources.items()]


class FilterModule:
    def filters(self):
        return {"lmstudio_declared_models": lmstudio_declared_models}
