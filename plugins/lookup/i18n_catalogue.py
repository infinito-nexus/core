from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.yaml import load_yaml
from utils.i18n.keyed import keyed_catalogue


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('i18n_catalogue', 'logout', 'roles/web-app-keycloak/files/logout_i18n.yml') }}
      {{ lookup('i18n_catalogue', 'team', role_path ~ '/locale/team.yml', catalogs=role_path) }}

    Returns the English strings of the source file and their translations
    as ``{code: {key: text, "dir": ...}}``. The first term is the ``msgctxt``
    prefix of the messages, the second the YAML file mapping each key to its
    English text, relative to the repository or absolute. Without
    ``catalogs`` the translations come from the ``core`` gettext catalogs;
    with it, from the ``<prefix>`` domain under ``<catalogs>/locale/``, which
    ``make i18n-extract root=<catalogs> domain=<prefix>`` writes.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 2:
            raise AnsibleError(
                "lookup('i18n_catalogue', prefix, source_file) expects exactly 2 terms"
            )
        root = Path(str((variables or {})["playbook_dir"]))
        prefix, source_file = (str(term) for term in terms)
        source = load_yaml(root / source_file)
        catalogs = kwargs.get("catalogs")
        return [
            keyed_catalogue(
                root,
                lambda key: f"{prefix}:{key}",
                source,
                root if catalogs is None else Path(str(catalogs)),
                "core" if catalogs is None else prefix,
            )
        ]
