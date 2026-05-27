from __future__ import annotations

import shutil

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """
    Resolve executable paths from command names.

    Usage:
      {{ lookup('command_path', 'baudolo') }}
      {{ lookup('command_path', 'baudolo', path='/custom/bin:/usr/bin') }}
    """

    def run(self, terms, variables=None, **kwargs):
        terms = terms or []
        if not terms:
            raise AnsibleError("command_path: requires at least one command term")

        search_path = str(
            kwargs.get(
                "path",
                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            )
        ).strip()

        results = []
        for term in terms:
            command = str(term).strip()
            if not command:
                raise AnsibleError("command_path: empty command term is not allowed")
            if any(ch.isspace() for ch in command):
                raise AnsibleError(
                    f"command_path: command must be a single token without whitespace: '{command}'"
                )

            resolved = shutil.which(command, path=search_path or None)
            if not resolved:
                raise AnsibleError(
                    f"command_path: command not found in PATH: '{command}' (PATH='{search_path}')"
                )
            results.append(resolved)

        return results
