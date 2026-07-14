"""Enforce that every ``*_CONTAINER`` var in a role's ``vars/main.yml``
resolves its container name from an owned source: either the config
lookup or the role's bare ``entity_name``.

Rationale
=========
A container's runtime name is owned by ``meta/services.yml`` via the
service's ``name:`` field, read canonically as::

    FOO_CONTAINER: "{{ lookup('config', application_id, 'services.foo.name') }}"

The bare entity-name form is equally accepted, since it resolves to the
same role-owned identity::

    FOO_CONTAINER: "{{ entity_name }}"

A shared-capable engine (redis, memcached, …) resolves its container
shared-aware through the engine lookup — the central provider's container
when shared, the embedded ``<entity>-<engine>`` sidecar otherwise::

    FOO_CONTAINER: "{{ lookup('engine', 'memcached', application_id, 'container') }}"

Hard-coding the name (``FOO_CONTAINER: "foo"``) or composing it inline
bypasses both: the value drifts from the role's declared identity. And if
the var *does* use the lookup but the service has no ``name:`` field, the
lookup renders empty and every ``container exec`` against it fails at
runtime.

This test therefore checks two things per ``*_CONTAINER`` var:

1. The value is the config-``name`` lookup OR the bare ``entity_name``
   form (``{{ entity_name }}`` / ``{{ <x> | get_entity_name }}``).
2. When the lookup form resolves ``<key>`` to a concrete service (a
   literal, or the role's ``entity_name``), that service declares
   ``name:`` in ``meta/services.yml``.

Per-line opt-out
================
Add ``# nocheck: container-var-name-lookup`` on the var's line or the
line immediately above. Legitimate uses: composite/multi-service names
(``{{ entity_name }}-{{ FOO_SERVICE }}``) and names owned by another
role's config.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_RULE = "container-var-name-lookup"

_CONTAINER_VAR_RE = re.compile(
    r"^(?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_CONTAINER):\s*(?P<val>\S.*?)\s*$"
)

_USES_NAME_LOOKUP_RE = re.compile(
    r"lookup\(\s*['\"]config['\"].*services\..*\.name", re.DOTALL
)

_USES_ENGINE_CONTAINER_RE = re.compile(
    r"lookup\(\s*['\"]engine['\"].*['\"]container['\"]", re.DOTALL
)

_ENTITY_NAME_RE = re.compile(
    r"^\{\{\s*(?:entity_name|[A-Za-z_]\w*\s*\|\s*get_entity_name)\s*\}\}$"
)

_SERVICE_KEY_RE = re.compile(r"services\.(?P<key>.*?)\.name", re.DOTALL)


def _is_vars_main(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and rel_path.endswith(
        f"/{ROLE_FILE_VARS_MAIN}"
    )


def _role_name(rel_path: str) -> str:
    return rel_path.split("/")[1]


def _resolve_service_key(raw_key: str, role_name: str) -> str | None:
    """Resolve the ``services.<key>.name`` key to a concrete service name.

    Returns None when the key is a composite or a non-literal role var the
    linter cannot evaluate statically (those need a nocheck)."""
    key = raw_key.strip()
    literal = re.fullmatch(r"['\"]?([a-z0-9][a-z0-9\-]*)['\"]?", key)
    if literal:
        return literal.group(1)
    if "entity_name" in key and "~" in key and "-" not in key:
        collapsed = re.sub(r"['\"~ ]", "", key)
        if collapsed == "entity_name":
            return get_entity_name(role_name)
    return None


def _service_declares_name(services_doc: dict, service_key: str) -> bool:
    entry = services_doc.get(service_key)
    return isinstance(entry, dict) and bool(str(entry.get("name", "")).strip())


class TestContainerVarNameLookup(unittest.TestCase):
    def test_container_vars_use_name_lookup(self) -> None:
        missing_lookup: list[tuple[str, int, str]] = []
        missing_name: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_vars_main(rel):
                continue

            role_name = _role_name(rel)
            services_path = PROJECT_ROOT / "roles" / role_name / ROLE_FILE_META_SERVICES
            services_doc = load_yaml_any(str(services_path), default_if_missing={})
            if not isinstance(services_doc, dict):
                services_doc = {}

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                match = _CONTAINER_VAR_RE.match(line)
                if not match:
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue

                value = match.group("val")
                if _ENTITY_NAME_RE.match(value.strip().strip("\"'")):
                    continue
                if _USES_ENGINE_CONTAINER_RE.search(value):
                    continue
                if not _USES_NAME_LOOKUP_RE.search(value):
                    missing_lookup.append((rel, idx + 1, match.group("name")))
                    continue

                key_match = _SERVICE_KEY_RE.search(value)
                if not key_match:
                    continue
                service_key = _resolve_service_key(key_match.group("key"), role_name)
                if service_key is None:
                    continue
                if not _service_declares_name(services_doc, service_key):
                    missing_name.append(
                        (
                            rel,
                            idx + 1,
                            f"{match.group('name')} -> services.{service_key}.name",
                        )
                    )

        messages: list[str] = []
        if missing_lookup:
            formatted = "\n".join(
                f"- {path}:{line_no}: {name}"
                for path, line_no, name in sorted(set(missing_lookup))
            )
            messages.append(
                "These `*_CONTAINER` vars do not resolve their name from an "
                "owned source. Use the config lookup:\n"
                "    FOO_CONTAINER: \"{{ lookup('config', application_id, "
                "'services.foo.name') }}\"\n"
                "or the bare entity name:\n"
                '    FOO_CONTAINER: "{{ entity_name }}"\n'
                "or, for a composite/foreign name, add "
                "`# nocheck: container-var-name-lookup`.\n\n"
                f"{formatted}"
            )
        if missing_name:
            formatted = "\n".join(
                f"- {path}:{line_no}: {detail}"
                for path, line_no, detail in sorted(set(missing_name))
            )
            messages.append(
                "These `*_CONTAINER` vars look up a service name that is not "
                "declared in the role's meta/services.yml (the lookup renders "
                "empty at runtime). Add a `name:` field to that service.\n\n"
                f"{formatted}"
            )

        if messages:
            self.fail("\n\n".join(messages))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
