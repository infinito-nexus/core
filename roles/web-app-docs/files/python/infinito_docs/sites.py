"""The built site trees on disk: what exists, what it was built from, and
which file a request maps to.

``Sites`` is a mixin of :class:`infinito_docs.library.Library` and reads only
``self.sites`` and ``self.translations``.
"""

from __future__ import annotations

import json


class Sites:
    def built_ref(self, version):
        stamp = self.sites / version / "ref"
        return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    def servable(self, version):
        return (self.sites / version / "html" / "index.html").is_file()

    def translation_ref(self, version, code):
        """Return the ref the translated site of ``code`` was built from.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code.
        """
        stamp = self.translations / version / code / "ref"
        return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    def translation_servable(self, version, code):
        return (self.translations / version / code / "html" / "index.html").is_file()

    def _language_index(self, version):
        try:
            payload = json.loads(
                (self.translations / version / "languages.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            return {}
        if isinstance(payload.get("known"), dict):
            return payload
        return {"known": payload, "translated": []}

    def _language_index_is_current(self, version) -> bool:
        """Whether the version's language index was written by this code.

        An index from before the split lists only the known languages, so the
        translated ones are unknown and no language can be requested. Calling
        that version current would leave it in that state forever, because only
        a build rewrites the index.

        Args:
            version: ``latest`` or a release tag.
        """
        path = self.translations / version / "languages.json"
        if not path.is_file():
            return True
        try:
            return "translated" in json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

    def languages(self, version):
        """Return the languages of ``version`` and the ones with a built site.

        Args:
            version: ``latest`` or a release tag.

        Returns:
            ``(known, built)``: every language code of the version mapped to
            its native name, and the codes whose translated site is servable.
        """
        known = self._language_index(version).get("known") or {}
        built = [
            code for code in sorted(known) if self.translation_servable(version, code)
        ]
        return known, built

    def translates(self, version, code):
        """Return whether ``version`` carries translations for ``code``.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code.
        """
        return code in (self._language_index(version).get("translated") or [])

    def resolve(self, version, rest):
        """Return the file a request for ``rest`` in ``version`` maps to.

        Args:
            version: a built version.
            rest: the request path below the version, already unquoted.

        Returns:
            The file inside the version's site, or ``None`` when the site has
            no such file or the path escapes it.
        """
        return self._resolve(self.sites / version / "html", rest)

    def resolve_translation(self, version, code, rest):
        return self._resolve(self.translations / version / code / "html", rest)

    def _resolve(self, site, rest):
        root = site.resolve()
        target = (root / rest).resolve()
        if target != root and root not in target.parents:
            return None
        if target.is_dir():
            target /= "index.html"
        return target if target.is_file() else None
