"""Move unnecessary meta dependencies to guarded include_role/import_role.

Run via ``python3 -m cli.fix.move_unnecessary_dependencies``. The
implementation is split across:

* ``__main__`` — argparse + per-role orchestration.
* ``analysis`` — provider / consumer static analysis.
* ``apply`` — YAML rewrite + include-block prepending.
* ``yaml_io`` — ruamel round-trip helpers + role-tree discovery.
"""
