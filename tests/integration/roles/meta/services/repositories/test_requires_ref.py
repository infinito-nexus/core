"""Integration guard: an entity in ``meta/services.yml`` that declares
``repository`` MUST also declare ``ref`` (and vice versa).

Rationale
---------

The unified entity-naming convention pairs the two dimensions:

- ``image`` + ``version`` → OCI image used as ``FROM image:version``.
- ``repository`` + ``ref`` → git source clone (``git clone --branch
  <ref> <repository>``).

Half-declarations are silent breakage waiting to happen: a Dockerfile
that reads ``ARG ... REPOSITORY/REF`` will render ``git clone --branch
"" "https://…"`` (empty branch flag) or attempt to clone an empty URL,
both of which surface only at build time and only on the variant the
role is built into. Catch it at lint time instead.

This guard is symmetric: declaring ``ref`` without ``repository``
fails just as loudly — the standalone ref has no source URL to
clone from.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


class TestRequiresRef(unittest.TestCase):
    def test_repository_and_ref_are_both_set_or_both_absent(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            services_path = role_dir / ROLE_FILE_META_SERVICES
            if not services_path.is_file():
                continue
            data = load_yaml_any(str(services_path), default_if_missing=None)
            if not isinstance(data, dict):
                continue

            for entity_key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                has_repo = "repository" in entry and entry["repository"] not in (
                    None,
                    "",
                )
                has_ref = "ref" in entry and entry["ref"] not in (None, "")
                if has_repo and not has_ref:
                    offenders.append(
                        f"{role_dir.name}: entity '{entity_key}' declares "
                        f"`repository` but is missing `ref`"
                    )
                elif has_ref and not has_repo:
                    offenders.append(
                        f"{role_dir.name}: entity '{entity_key}' declares "
                        f"`ref` but is missing `repository`"
                    )

        if offenders:
            self.fail(
                f"{len(offenders)} entity/entities violate the "
                f"`repository`↔`ref` pairing:\n"
                + "\n".join(f"- {o}" for o in offenders)
            )
