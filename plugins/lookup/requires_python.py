"""
Ansible lookup plugin: requires_python

Args:
    terms: none.

Returns:
    The ``requires-python`` spec of pyproject.toml at the repository root.
"""

from __future__ import annotations

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT
from utils.requires_python import requires_python


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if terms:
            raise AnsibleError("requires_python lookup takes no terms")
        return [requires_python(PROJECT_ROOT)]
