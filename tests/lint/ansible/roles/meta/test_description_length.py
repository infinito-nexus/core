"""Enforce a uniform schema for ``galaxy_info.description`` in every
role's ``meta/main.yml``.

The description feeds the root-README roles overview and ``infinito``
role listings, so it MUST read fluently down a table column. The schema:

* a **noun phrase** describing the FUNCTION of the software the role
  deploys (or, for glue/infra roles, the role's own artefact) --
  it MUST NOT start with a verb (``Deploys``, ``Installs``, ``Runs`` …);
* at most **120 characters**, one line;
* **no trailing period**;
* plain factual tone, no marketing, no repetition of the role/product
  name (that already sits in the overview's Name column).
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.description import violations
from utils.roles.mapping import ROLE_FILE_META_MAIN

from . import PROJECT_ROOT


def _description(role_dir) -> str:
    data = (
        load_yaml_any(str(role_dir / ROLE_FILE_META_MAIN), default_if_missing={}) or {}
    )
    galaxy = data.get("galaxy_info") if isinstance(data, dict) else None
    description = galaxy.get("description") if isinstance(galaxy, dict) else None
    return description.strip() if isinstance(description, str) else ""


class TestDescriptionSchema(unittest.TestCase):
    def test_descriptions_follow_the_uniform_schema(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if not role_dir.is_dir():
                continue
            description = _description(role_dir)
            if not description:
                continue
            problems = violations(description)
            if problems:
                offenders.append(f"  - {role_dir.name}: {', '.join(problems)}")

        self.assertFalse(
            offenders,
            f"{len(offenders)} role(s) violate the galaxy_info.description "
            f"schema in {ROLE_FILE_META_MAIN}.\n"
            "A description MUST be a noun phrase describing the FUNCTION of "
            "the software the role deploys (or the role's own artefact), MUST "
            "NOT start with a verb, MUST fit in 120 characters on one line, "
            "and MUST NOT end with a period. Drop marketing prose and do not "
            "repeat the role name.\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
