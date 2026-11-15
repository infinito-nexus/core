from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.i18n.extract import rbac_context
from utils.i18n.keyed import keyed_catalogue


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('rbac_i18n_catalogue', catalogue) }}

    Returns the role descriptions of a ``rbac_access_catalogue`` result and
    their translations from the ``core`` gettext catalogs as
    ``{code: {"<application_id>/<role>": text, "dir": ...}}``.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 1 or not isinstance(terms[0], dict):
            raise AnsibleError(
                "lookup('rbac_i18n_catalogue', catalogue) expects one catalogue mapping"
            )
        root = Path(str((variables or {})["playbook_dir"]))
        source = {
            f"{application_id}/{role['role']}": role["description"]
            for application_id, entry in terms[0].items()
            for role in entry["roles"]
            if role["description"]
        }
        return [
            keyed_catalogue(
                root, lambda key: rbac_context(*key.split("/", 1)), source, root, "core"
            )
        ]
