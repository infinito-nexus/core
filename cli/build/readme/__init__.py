"""Role README schema, section parsing, Cosmos derivation, and generation.

``templates/roles/README.md.j2.tmpl`` is the single source of truth for the
role-README structure. :mod:`cli.build.readme.schema` derives the
required/optional section set from it; the lint
(``tests/lint/ansible/roles/test_readme.py``) and the generator
(``python -m cli.build.readme``) both consume that same schema so the
three never drift.
"""
