from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.files import read_text
from utils.i18n.catalog import catalog_path, read_catalog, translations

REWRITTEN = re.compile(r"[*`\[\]!<>|#\"'‘’“”]|--|\.\.\.")
MINIMUM_LENGTH = 30


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('i18n_sample', 'docs', 'de', 'README.md', 5) }}

    Returns up to ``count`` translated messages of ``domain`` in language
    ``code`` whose source occurs verbatim in the repository file
    ``source_file``, as ``{source: translation}``. Messages carrying markup,
    quotes, dashes or ellipses are skipped, because the renderer rewrites
    them and a page could never contain them verbatim.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 4:
            raise AnsibleError(
                "lookup('i18n_sample', domain, code, source_file, count) expects exactly 4 terms"
            )
        domain, code, source_file, count = terms
        root = Path(str((variables or {})["playbook_dir"]))
        text = read_text(str(root / str(source_file)))
        path = catalog_path(root, str(code), str(domain))
        sample: dict[str, str] = {}
        if not path.is_file():
            return [sample]
        for (_, source), target in sorted(translations(read_catalog(path)).items()):
            if (
                len(source) >= MINIMUM_LENGTH
                and source in text
                and not REWRITTEN.search(source + target)
            ):
                sample[source] = target
                if len(sample) >= int(count):
                    break
        return [sample]
