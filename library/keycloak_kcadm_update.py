#!/usr/bin/python


import json
import re
import subprocess
import time
from copy import deepcopy

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.kcadm_json import json_from_noisy_stdout

NO_SUCH_CONTAINER_RE = re.compile(r"no such container", re.IGNORECASE)
DEAD_CID_MAX_RETRIES = 80
DEAD_CID_RETRY_DELAY = 3

DOCUMENTATION = r"""
---
module: keycloak_kcadm_update

short_description: Create or update Keycloak clients/components/client-scopes/realms via kcadm.

description:
  - Generic "create or update" module for Keycloak objects using kcadm.
  - Resolves the object by a lookup field, reads current state if it exists,
    deep-merges the desired state on top (optionally only a sub-path),
    preserves immutable fields, applies forced attributes and then
    updates or creates the object.

options:
  object_kind:
    description: Kind of the Keycloak object.
    type: str
    required: True
    choices: [client, component, client-scope, realm]
  lookup_value:
    description: Value to look up the object (e.g. clientId, component name, realm id).
    type: str
    required: True
  desired:
    description: Desired object dictionary.
    type: dict
    required: True
  lookup_field:
    description:
      - Lookup field name.
      - Defaults depend on object_kind:
      - client -> clientId
      - component -> name
      - client-scope -> name
      - realm -> id
    type: str
    required: False
  merge_path:
    description:
      - If set (e.g. C(config)), only this subkey is merged into the current object.
      - If omitted, the whole object is merged.
    type: str
    required: False
  force_attrs:
    description:
      - Attributes that are always applied last on the final payload.
    type: dict
    required: False
  kcadm_exec:
    description:
      - Command to execute kcadm.
      - E.g. C(container exec -i keycloak /opt/keycloak/bin/kcadm.sh).
    type: str
    required: True
  realm:
    description:
      - Realm name used for non-realm objects.
    type: str
    required: False
  assert_mode:
    description:
      - If true, additional safety checks are applied (e.g. providerId match for components).
    type: bool
    required: False
    default: True
  cid_resolve_cmd:
    description:
      - Swarm-only. Shell command that prints a fresh, live, healthy container id.
      - When a kcadm exec aborts with 'No such container' (the cached swarm id
        was rescheduled mid-block), this command is re-run to obtain a live id
        and the exec is retried.
    type: str
    required: False
  current_cid:
    description:
      - Swarm-only. The container id currently embedded in C(kcadm_exec).
      - Used as the literal token to swap for a freshly resolved id on retry.
    type: str
    required: False

author:
  - Your Name
"""

RETURN = r"""
changed:
  description: Whether the object was created or updated.
  type: bool
  returned: always
object_exists:
  description: Whether the object was found by the lookup.
  type: bool
  returned: always
object_id:
  description: Resolved object id (if exists).
  type: str
  returned: always
result:
  description: The final payload that was sent to Keycloak.
  type: dict
  returned: always
"""


def _shell(cmd, check):
    rc = subprocess.run(  # noqa: S602 - host-trusted argv; kcadm wrapper needs shell pipes/&&
        cmd,
        shell=True,
        check=check,
        capture_output=True,
    )
    stdout = rc.stdout.decode("utf-8", errors="replace").strip()
    stderr = rc.stderr.decode("utf-8", errors="replace").strip()
    return rc.returncode, stdout, stderr


def _resolve_live_cid(module):
    """Resolve a fresh, healthy container id via the swarm-service resolver.

    Returns the new id or "" when no resolver hint was provided or the
    resolver yielded nothing.
    """
    state = getattr(module, "_kcadm_cid_state", None)
    if not state or not state.get("cid_resolve_cmd"):
        return ""
    _rc, out, _err = _shell(state["cid_resolve_cmd"], check=False)
    return (out or "").strip()


def run_kcadm(module, cmd, ignore_rc=False):
    """Run a shell command for kcadm.

    In swarm the keycloak service runs multiple replicas that swarm may
    reschedule between any two of the sequential execs this module issues,
    so a container id resolved earlier can die mid-block. When that happens
    `container exec` aborts with 'No such container' BEFORE kcadm runs; if a
    resolver hint is present, re-resolve a live healthy id, splice it into
    the command and retry (bounded) instead of failing the whole client
    update on an ephemeral id.
    """
    state = getattr(module, "_kcadm_cid_state", None)
    attempt_cmd = cmd

    for attempt in range(DEAD_CID_MAX_RETRIES + 1):
        rc, stdout, stderr = _shell(attempt_cmd, check=False)

        retryable = (
            rc != 0
            and state
            and state.get("cid_resolve_cmd")
            and state.get("current_cid")
            and NO_SUCH_CONTAINER_RE.search(stderr or "")
            and attempt < DEAD_CID_MAX_RETRIES
        )
        if not retryable:
            if rc != 0 and not ignore_rc:
                raise subprocess.CalledProcessError(rc, attempt_cmd, stdout, stderr)
            return rc, stdout, stderr

        time.sleep(DEAD_CID_RETRY_DELAY)
        new_cid = _resolve_live_cid(module)
        if not new_cid or new_cid == state["current_cid"]:
            continue
        old_cid = state["current_cid"]
        attempt_cmd = cmd.replace(old_cid, new_cid)
        cmd = attempt_cmd
        state["current_cid"] = new_cid

    return rc, stdout, stderr


def deep_merge(a, b):
    """Recursive dict merge similar to Ansible's combine(recursive=True)."""
    result = deepcopy(a)
    for k, v in (b or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def get_api_and_lookup_field(object_kind, lookup_field):
    if object_kind == "client":
        api = "clients"
        default_lookup = "clientId"
    elif object_kind == "component":
        api = "components"
        default_lookup = "name"
    elif object_kind == "client-scope":
        api = "client-scopes"
        default_lookup = "name"
    elif object_kind == "realm":
        api = "realms"
        default_lookup = "id"
    else:
        api = ""
        default_lookup = ""
    return api, (lookup_field or default_lookup)


def resolve_object_id(
    module, object_kind, api, lookup_field, lookup_value, realm, kcadm_exec
):
    """Return (object_id, exists_flag)."""
    if lookup_field == "id":
        obj_id = str(lookup_value).strip()
        if not obj_id:
            return "", False
        return obj_id, True

    if object_kind == "realm":
        return str(lookup_value), True

    if object_kind == "client-scope":
        cmd = f"{kcadm_exec} get client-scopes -r {realm} --format json"
        rc, out, _err = run_kcadm(module, cmd, ignore_rc=True)
        if rc != 0 or not out:
            return "", False
        scopes = json_from_noisy_stdout(out)
        for obj in scopes:
            if obj.get(lookup_field) == lookup_value:
                return obj.get("id", ""), True
        return "", False

    if object_kind == "client":
        cmd = f"{kcadm_exec} get clients -r {realm} --format json"
        rc, out, _err = run_kcadm(module, cmd, ignore_rc=True)
        if rc != 0 or not out:
            return "", False
        clients = json_from_noisy_stdout(out)
        for obj in clients:
            if obj.get(lookup_field) == lookup_value:
                return obj.get("id", ""), True
        return "", False

    if object_kind == "component":
        cmd = f"{kcadm_exec} get components -r {realm} --format json"
        rc, out, _err = run_kcadm(module, cmd, ignore_rc=True)
        if rc != 0 or not out:
            return "", False
        comps = json_from_noisy_stdout(out)
        for obj in comps:
            if obj.get(lookup_field) == lookup_value:
                return obj.get("id", ""), True
        return "", False

    cmd = (
        f"{kcadm_exec} get {api} -r {realm} "
        f"--query '{lookup_field}={lookup_value}' "
        f"--fields id --format json"
    )
    rc, out, _err = run_kcadm(module, cmd, ignore_rc=True)
    if rc != 0 or not out:
        return "", False

    data = json_from_noisy_stdout(out)
    if not data:
        return "", False
    return data[0].get("id", ""), True


def get_current_object(module, object_kind, api, object_id, realm, kcadm_exec):
    if object_kind == "realm":
        cmd = f"{kcadm_exec} get {api}/{object_id} --format json"
    else:
        cmd = f"{kcadm_exec} get {api}/{object_id} -r {realm} --format json"
    _rc, out, _err = run_kcadm(module, cmd)
    return json_from_noisy_stdout(out)


def send_update(module, object_kind, api, object_id, realm, kcadm_exec, payload):
    payload_json = json.dumps(payload)
    if object_kind == "realm":
        cmd = (
            f"cat <<'JSON' | {kcadm_exec} update {api}/{object_id} -f -\n"
            f"{payload_json}\nJSON"
        )
    else:
        cmd = (
            f"cat <<'JSON' | {kcadm_exec} update {api}/{object_id} -r {realm} -f -\n"
            f"{payload_json}\nJSON"
        )
    return run_kcadm(module, cmd, ignore_rc=True)


def send_create(module, object_kind, api, realm, kcadm_exec, payload):
    payload_json = json.dumps(payload)
    if object_kind == "realm":
        cmd = f"cat <<'JSON' | {kcadm_exec} create {api} -f -\n{payload_json}\nJSON"
    else:
        cmd = (
            f"cat <<'JSON' | {kcadm_exec} create {api} -r {realm} -f -\n"
            f"{payload_json}\nJSON"
        )
    return run_kcadm(module, cmd, ignore_rc=True)


def run_module():
    module_args = {
        "object_kind": {"type": "str", "required": True},
        "lookup_value": {"type": "str", "required": True},
        "desired": {"type": "dict", "required": True},
        "lookup_field": {"type": "str", "required": False, "default": None},
        "merge_path": {"type": "str", "required": False, "default": None},
        "force_attrs": {"type": "dict", "required": False, "default": None},
        "kcadm_exec": {"type": "str", "required": True},
        "realm": {"type": "str", "required": False, "default": None},
        "assert_mode": {"type": "bool", "required": False, "default": True},
        "cid_resolve_cmd": {"type": "str", "required": False, "default": None},
        "current_cid": {"type": "str", "required": False, "default": None},
    }

    result = {
        "changed": False,
        "object_exists": False,
        "object_id": "",
        "result": {},
    }

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=False)

    object_kind = module.params["object_kind"]
    lookup_value = module.params["lookup_value"]
    desired = module.params["desired"] or {}
    lookup_field = module.params["lookup_field"]
    merge_path = module.params["merge_path"]
    force_attrs = module.params["force_attrs"] or {}
    kcadm_exec = module.params["kcadm_exec"]
    realm = module.params["realm"]
    assert_mode = module.params["assert_mode"]

    module._kcadm_cid_state = {
        "cid_resolve_cmd": module.params.get("cid_resolve_cmd"),
        "current_cid": (module.params.get("current_cid") or "").strip(),
    }

    if object_kind != "realm" and not realm:
        module.fail_json(msg="Parameter 'realm' is required for non-realm objects.")

    api, eff_lookup_field = get_api_and_lookup_field(object_kind, lookup_field)
    if not api:
        module.fail_json(msg="Unsupported object_kind", object_kind=object_kind)

    object_id, exists = resolve_object_id(
        module, object_kind, api, eff_lookup_field, lookup_value, realm, kcadm_exec
    )
    result["object_exists"] = exists
    result["object_id"] = object_id

    if not exists or not object_id:
        desired_obj = deepcopy(desired)

        if object_kind == "component":
            desired_obj.pop("subComponents", None)

        if force_attrs:
            desired_obj = deep_merge(desired_obj, force_attrs)

        rc, out, err = send_create(
            module, object_kind, api, realm, kcadm_exec, desired_obj
        )

        if rc != 0:
            err_l = (err or "").lower()
            already_exists_markers = ["already exists", "exists with same", "conflict"]
            if any(m in err_l for m in already_exists_markers):
                object_id2, exists2 = resolve_object_id(
                    module,
                    object_kind,
                    api,
                    eff_lookup_field,
                    lookup_value,
                    realm,
                    kcadm_exec,
                )
                if exists2 and object_id2:
                    object_id = object_id2
                    exists = True
                    result["object_exists"] = True
                    result["object_id"] = object_id
                else:
                    module.fail_json(
                        msg="Create failed with 'already exists' but re-resolve did not find object id",
                        rc=rc,
                        stdout=out,
                        stderr=err,
                        payload=desired_obj,
                    )
            else:
                module.fail_json(
                    msg="Failed to create Keycloak object",
                    rc=rc,
                    stdout=out,
                    stderr=err,
                    payload=desired_obj,
                )

        if not exists or not object_id:
            result["changed"] = True
            result["result"] = desired_obj
            module.exit_json(**result)

    cur_obj = get_current_object(module, object_kind, api, object_id, realm, kcadm_exec)

    if assert_mode and object_kind == "component":
        cur_provider = cur_obj.get("providerId", "")
        des_provider = desired.get("providerId", "")
        if cur_provider and des_provider and cur_provider != des_provider:
            module.fail_json(
                msg="Refusing to update component due to providerId mismatch",
                current_providerId=cur_provider,
                desired_providerId=des_provider,
            )

    if merge_path:
        merge_payload = {merge_path: deepcopy(desired.get(merge_path, {}))}
    else:
        merge_payload = deepcopy(desired)

    desired_obj = deep_merge(cur_obj, merge_payload)

    if object_kind == "client":
        for k in ["id", "clientId"]:
            if k in cur_obj:
                desired_obj[k] = cur_obj[k]
    elif object_kind == "component":
        for k in ["id", "providerId", "providerType", "parentId"]:
            if k in cur_obj:
                desired_obj[k] = cur_obj[k]
        desired_obj.pop("subComponents", None)
    elif object_kind == "client-scope":
        for k in ["id", "name"]:
            if k in cur_obj:
                desired_obj[k] = cur_obj[k]
    elif object_kind == "realm":
        for k in ["id", "realm"]:
            if k in cur_obj:
                desired_obj[k] = cur_obj[k]

    if force_attrs:
        desired_obj = deep_merge(desired_obj, force_attrs)

    rc, out, err = send_update(
        module, object_kind, api, object_id, realm, kcadm_exec, desired_obj
    )
    if rc != 0:
        module.fail_json(
            msg="Failed to update Keycloak object",
            rc=rc,
            stdout=out,
            stderr=err,
            payload=desired_obj,
        )

    result["changed"] = True
    result["result"] = desired_obj
    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
