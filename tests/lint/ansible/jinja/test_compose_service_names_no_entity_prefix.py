"""Forbid the ``<entity_name>-`` prefix in compose SERVICE names.

Compose service names are role-scoped: the entity prefix carries no
information inside the stack, breaks the ``services.<name>.*`` resource
and image key convention (``resource_filter`` resolves the compose
service name first), and leaks into swarm DNS as the redundant
``<entity>_<entity>-<name>``. The docker ``container_name`` (host-global)
MAY keep the prefix via the ``compose_only`` lookup; the ``service_name``
itself must be the short form:

    {% set service_name = 'backend' %}      # OK
    {% set service_name = 'kix-backend' %}  # forbidden

``service_name`` set from a role var (e.g. ``KIX_BACKEND_CONTAINER``) is
resolved against literal assignments in the role's ``vars/main.yml``.

Per-line opt-out: ``# nocheck: compose-service-name-entity-prefix`` on the
offending ``{% set service_name = ... %}`` line or the immediately
preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_RULE = "compose-service-name-entity-prefix"

_SET_LITERAL = re.compile(r"\{%[+-]?\s*set service_name = '([^']+)'\s*[+-]?%\}")
_SET_VAR = re.compile(r"\{%[+-]?\s*set service_name = ([A-Z][A-Z0-9_]*)\s*[+-]?%\}")
_VAR_LITERAL = re.compile(r'^([A-Z][A-Z0-9_]*):\s*"([a-z0-9_-]+)"\s*$', re.MULTILINE)


def _entity_name(role_name: str) -> str:
    for prefix in ("web-app-", "web-svc-", "svc-", "sys-"):
        if role_name.startswith(prefix):
            return role_name[len(prefix) :]
    return role_name


class TestComposeServiceNamesNoEntityPrefix(unittest.TestCase):
    def test_service_names_carry_no_entity_prefix(self) -> None:
        offenders: list[str] = []
        roles_dir = PROJECT_ROOT / "roles"
        for template in sorted(roles_dir.glob(f"*/{ROLE_FILE_TEMPL_COMPOSE}")):
            role_name = template.parent.parent.name
            entity = _entity_name(role_name)
            text = read_text(str(template))
            lines = text.splitlines()

            var_map: dict[str, str] = {}
            vars_file = roles_dir / role_name / ROLE_FILE_VARS_MAIN
            if vars_file.is_file():
                var_map = dict(_VAR_LITERAL.findall(read_text(str(vars_file))))

            for lineno, line in enumerate(lines, 1):
                literal = _SET_LITERAL.search(line)
                via_var = _SET_VAR.search(line)
                if literal:
                    name, source = literal.group(1), "literal"
                elif via_var:
                    var = via_var.group(1)
                    name, source = var_map.get(var, ""), var
                else:
                    continue
                if not name.startswith(entity + "-"):
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                rel = template.relative_to(PROJECT_ROOT)
                offenders.append(
                    f"{rel}:{lineno}: service '{name}' (via {source}) carries "
                    f"the entity prefix '{entity}-'"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} compose service name(s) carry their role's "
                "entity prefix. Compose service names are stack-scoped: use "
                "the short form ({% set service_name = 'backend' %}); keep "
                "the prefixed name only for the docker container_name via "
                "the compose_only lookup.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
