from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.i18n.keyed import source_keyed_catalogues


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('i18n_content', 'role:', 'menu:') }}

    Returns ``{code: {english: translation}}`` built from the ``core``
    gettext catalogs for every message whose ``msgctxt`` starts with one of
    the given prefixes, for every language that translates at least one.
    A term may also be a list of prefixes.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms:
            raise AnsibleError(
                "lookup('i18n_content', prefix, ...) expects at least 1 term"
            )
        root = Path(str((variables or {})["playbook_dir"]))
        prefixes = tuple(
            str(prefix)
            for term in terms
            for prefix in (term if isinstance(term, list) else [term])
        )
        return [source_keyed_catalogues(root, prefixes)]
