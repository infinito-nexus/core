"""Ensure many directories exist in one module call.

Args:
    entries: list of ``{path, mode, owner, group}``, each path with its own
        attributes; mutually exclusive with ``paths``.
    paths: list of paths that all receive ``mode``, ``owner`` and ``group``.
    mode: mode of every path in ``paths``.
    owner: owner of every path in ``paths``.
    group: group of every path in ``paths``.

    Every path is handled like ``ansible.builtin.file`` with
    ``state: directory``: a symlink is followed, a missing path is created
    together with its missing parents, which receive the same attributes, an
    existing directory gets every given attribute that differs, and an
    attribute left out stays as found.

Returns:
    changed_paths: the paths that were created or whose attributes changed.
    diff: one ``before``/``after`` record per changed path, in diff mode.
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.directory_batch import ATTRIBUTE_SPEC, ATTRIBUTES, ensure_all

ARGUMENT_SPEC = {
    "entries": {
        "type": "list",
        "elements": "dict",
        "options": {"path": {"type": "path", "required": True}, **ATTRIBUTE_SPEC},
    },
    "paths": {"type": "list", "elements": "path"},
    **ATTRIBUTE_SPEC,
}

MUTUALLY_EXCLUSIVE = [["entries", name] for name in ("paths", *ATTRIBUTES)]

REQUIRED_ONE_OF = [["entries", "paths"]]


def requested_entries(params):
    if params["entries"] is not None:
        return params["entries"]
    return [
        {"path": path, **{name: params[name] for name in ATTRIBUTES}}
        for path in params["paths"]
    ]


def main():
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        mutually_exclusive=MUTUALLY_EXCLUSIVE,
        required_one_of=REQUIRED_ONE_OF,
        supports_check_mode=True,
    )
    changed_paths, diffs = ensure_all(module, requested_entries(module.params))
    result = {"changed": bool(changed_paths), "changed_paths": changed_paths}
    if module._diff:
        result["diff"] = diffs
    module.exit_json(**result)


if __name__ == "__main__":
    main()
