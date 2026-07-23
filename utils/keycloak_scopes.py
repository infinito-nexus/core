"""Client-scope list convergence for keycloak_kcadm_update.

A client PUT ignores default/optionalClientScopes (sub-resources with their
own endpoints; verified against a live deploy) — these helpers converge them
explicitly: DELETE unassigns, bodyless PUT assigns, removals first so a scope
can move between the two lists.

``run_kcadm`` is injected by the calling module (it owns retry/CID-recovery
semantics); every helper takes it as its first argument.
"""

from ansible.module_utils.kcadm_json import json_from_noisy_stdout


def named_id_map(run_kcadm, module, cmd):
    """Run a kcadm list command and return a {name: id} map (empty on noise)."""
    _rc, out, _err = run_kcadm(module, cmd, ignore_rc=True)
    try:
        data = json_from_noisy_stdout(out)
    except ValueError:
        data = []
    return {
        item["name"]: item["id"]
        for item in data or []
        if isinstance(item, dict) and item.get("name") and item.get("id")
    }


def converge_client_scope_lists(run_kcadm, module, object_id, desired, realm, kcadm_exec):
    """Converge a client's default/optional client-scope lists to ``desired``."""
    plans = []
    for field, kind in (
        ("defaultClientScopes", "default-client-scopes"),
        ("optionalClientScopes", "optional-client-scopes"),
    ):
        if field not in desired:
            continue
        wanted = {str(name) for name in (desired.get(field) or [])}
        current = named_id_map(
            run_kcadm,
            module,
            f"{kcadm_exec} get clients/{object_id}/{kind} -r {realm} --format json",
        )
        plans.append((kind, wanted, current))

    changed = False
    for kind, wanted, current in plans:
        for name in sorted(set(current) - wanted):
            rc, out, err = run_kcadm(
                module,
                f"{kcadm_exec} delete clients/{object_id}/{kind}/{current[name]} -r {realm}",
                ignore_rc=True,
            )
            if rc != 0:
                module.fail_json(
                    msg="Failed to unassign client scope",
                    scope=name,
                    scope_kind=kind,
                    rc=rc,
                    stdout=out,
                    stderr=err,
                )
            changed = True

    catalog = None
    for kind, wanted, current in plans:
        for name in sorted(wanted - set(current)):
            if catalog is None:
                catalog = named_id_map(
                    run_kcadm,
                    module,
                    f"{kcadm_exec} get client-scopes -r {realm} --format json",
                )
            scope_id = catalog.get(name)
            if not scope_id:
                module.fail_json(
                    msg="Desired client scope does not exist in the realm",
                    scope=name,
                    scope_kind=kind,
                )
            rc, out, err = run_kcadm(
                module,
                f"{kcadm_exec} update clients/{object_id}/{kind}/{scope_id} -r {realm}",
                ignore_rc=True,
            )
            if rc != 0:
                module.fail_json(
                    msg="Failed to assign client scope",
                    scope=name,
                    scope_kind=kind,
                    rc=rc,
                    stdout=out,
                    stderr=err,
                )
            changed = True
    return changed
