from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.docker.paths_utils import get_docker_paths


def _as_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _deep_get(d: dict[str, Any], path: str) -> Any:
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            raise AnsibleError(f"lookup('container'): invalid path '{path}'")
        cur = cur[key]
    return cur


class LookupModule(LookupBase):
    """
    lookup('container', application_id[, path])

    path can be:
      - 'directories' / 'files' (returns sub-dict)
      - 'directories.instance' (returns leaf)
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) > 2:
            raise AnsibleError("lookup('container', application_id[, path])")

        application_id = _as_str(terms[0])
        if not application_id:
            raise AnsibleError("lookup('container'): application_id is empty")

        raw_base = (variables or {}).get("DIR_COMPOSITIONS")
        # DIR_COMPOSITIONS is itself a Jinja expression in swarm mode; lookup vars arrive un-templated.
        if isinstance(raw_base, str) and "{{" in raw_base and self._templar is not None:
            raw_base = self._templar.template(raw_base)
        base = _as_str(raw_base)
        if not base:
            raise AnsibleError("lookup('container'): DIR_COMPOSITIONS not set")

        paths = get_docker_paths(application_id, base)

        if len(terms) == 2:
            path = _as_str(terms[1])
            if not path:
                raise AnsibleError("lookup('container'): path is empty")
            return [_deep_get(paths, path)]

        return [paths]
