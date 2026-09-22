from __future__ import annotations


def i18n_content_templates(
    catalogues: dict, directory: str, template: str
) -> list[dict]:
    """Return one ``render_replicated_templates`` entry per content catalog.

    Args:
        catalogues: the ``lookup('i18n_content', ...)`` result, keyed by language.
        directory: host directory port-ui mounts as ``i18n/content``.
        template: template rendering the catalog named by ``language``.
    """
    return [
        {
            "src": template,
            "dest": f"{directory.rstrip('/')}/{code}.yaml",
            "language": code,
            "mode": "0644",
        }
        for code in sorted(catalogues)
    ]


class FilterModule:
    def filters(self):
        return {"i18n_content_templates": i18n_content_templates}
