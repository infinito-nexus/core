"""The ``core`` catalog messages the deploy rendered, picked by the request's language."""

from __future__ import annotations

SOURCE_LANGUAGE = "en"


def languages(accept_language: str) -> list[str]:
    """Return the language codes of an ``Accept-Language`` header, best first.

    Args:
        accept_language: the header value, possibly empty.
    """
    weighted = []
    for index, part in enumerate(accept_language.split(",")):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag or tag == "*":
            continue
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        weighted.append((-quality, index, tag))
    codes = []
    for _, _, tag in sorted(weighted):
        for code in (tag, tag.split("-")[0]):
            if code not in codes:
                codes.append(code)
    return codes


class Messages:
    """The texts of one language, falling back to English per key.

    Args:
        catalogue: language code mapped to ``{key: text, "dir": direction}``.
        rbac: language code mapped to ``{"<application>/<role>": description}``.
        accept_language: the request's ``Accept-Language`` header.
    """

    def __init__(
        self,
        catalogue: dict[str, dict[str, str]],
        rbac: dict[str, dict[str, str]],
        accept_language: str,
    ) -> None:
        self.code = next(
            (c for c in languages(accept_language) if c in catalogue), SOURCE_LANGUAGE
        )
        self._texts = {**catalogue[SOURCE_LANGUAGE], **catalogue.get(self.code, {})}
        self._rbac = {**rbac.get(SOURCE_LANGUAGE, {}), **rbac.get(self.code, {})}
        self.direction = self._texts.get("dir", "ltr")

    def __call__(self, key: str, **values: str) -> str:
        text = self._texts[key]
        return text.format(**values) if values else text

    def role(self, application: str, role: str, fallback: str) -> str:
        """Return the translated description of an application role.

        Args:
            application: application id.
            role: role name.
            fallback: the English description from ``meta/rbac.yml``.
        """
        return self._rbac.get(f"{application}/{role}") or fallback
