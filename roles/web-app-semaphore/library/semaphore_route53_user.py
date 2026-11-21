"""Args:
    user: the IAM user name, ``ws-<id>`` of the workspace.
    state: ``present`` converges the user, its one inline policy and its one
        access key; ``absent`` deletes its access keys, its inline policies
        and the user.
    policy_name: the name of the inline policy, for ``present``.
    policy: the exact policy document, for ``present``.
    held_access_key_id: the access key id the workspace record holds with its
        secret, empty when it holds none, for ``present``.
    admin_access_key_id: the access key id of the AWS identity that manages
        the workspace IAM users.
    admin_secret_access_key: its secret access key.

Returns:
    changes: the IAM write actions the call ran, or would run in check mode.
    minted: whether ``present`` created a new access key.
    access_key_id: the access key the user holds after ``present``.
    secret_access_key: the secret of a minted key, null when the held key
        stays or in check mode.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

from ansible.module_utils.aws_api import AwsError, iam
from ansible.module_utils.basic import AnsibleModule

ARGUMENT_SPEC = {
    "user": {"type": "str", "required": True},
    "state": {"type": "str", "required": True, "choices": ["present", "absent"]},
    "policy_name": {"type": "str"},
    "policy": {"type": "dict"},
    "held_access_key_id": {"type": "str", "no_log": False},
    "admin_access_key_id": {"type": "str", "required": True, "no_log": True},
    "admin_secret_access_key": {"type": "str", "required": True, "no_log": True},
}
REQUIRED_IF = [("state", "present", ("policy_name", "policy", "held_access_key_id"))]
ACTIVE = "Active"


class Session:
    """Args:
    credentials: ``access_key_id`` and ``secret_access_key`` of the admin.
    check_mode: whether writes are recorded and skipped.
    """

    def __init__(self, credentials: dict, check_mode: bool):
        self.credentials = credentials
        self.check_mode = check_mode
        self.changes: list[str] = []

    def read(self, action: str, **params):
        return iam(self.credentials, action, params)

    def write(self, action: str, **params):
        self.changes.append(action)
        return None if self.check_mode else iam(self.credentials, action, params)


def _exists(session: Session, user: str) -> bool:
    try:
        session.read("GetUser", UserName=user)
    except AwsError as error:
        if error.code == "NoSuchEntity":
            return False
        raise
    return True


def _members(session: Session, action: str, user: str, field: str) -> list:
    members: list = []
    marker = None
    while True:
        params = {"UserName": user, **({"Marker": marker} if marker else {})}
        result = session.read(action, **params).find(f"{action}Result")
        members += list(result.iterfind(f"{field}/member"))
        if result.findtext("IsTruncated") != "true":
            return members
        marker = result.findtext("Marker")


def _policy(session: Session, user: str, name: str, policy: dict) -> None:
    names = [m.text for m in _members(session, "ListUserPolicies", user, "PolicyNames")]
    for other in names:
        if other != name:
            session.write("DeleteUserPolicy", UserName=user, PolicyName=other)
    if name in names:
        held = session.read("GetUserPolicy", UserName=user, PolicyName=name)
        document = held.findtext("GetUserPolicyResult/PolicyDocument")
        if json.loads(unquote(document)) == policy:
            return
    session.write(
        "PutUserPolicy",
        UserName=user,
        PolicyName=name,
        PolicyDocument=json.dumps(policy, separators=(",", ":")),
    )


def _key(session: Session, user: str, held: str) -> dict:
    keys = {
        m.findtext("AccessKeyId"): m.findtext("Status")
        for m in _members(session, "ListAccessKeys", user, "AccessKeyMetadata")
    }
    kept = held if held and keys.get(held) == ACTIVE else None
    for key_id in keys:
        if key_id != kept:
            session.write("DeleteAccessKey", UserName=user, AccessKeyId=key_id)
    if kept:
        return {"minted": False, "access_key_id": kept, "secret_access_key": None}
    created = session.write("CreateAccessKey", UserName=user)
    if created is None:
        return {"minted": True, "access_key_id": None, "secret_access_key": None}
    key = created.find("CreateAccessKeyResult/AccessKey")
    return {
        "minted": True,
        "access_key_id": key.findtext("AccessKeyId"),
        "secret_access_key": key.findtext("SecretAccessKey"),
    }


def present(session: Session, user: str, name: str, policy: dict, held: str) -> dict:
    """Args:
        session: the IAM session of the admin.
        user: the IAM user name.
        name: the name of its inline policy.
        policy: the exact policy document.
        held: the access key id the workspace record holds, empty for none.

    Returns:
        ``minted``, ``access_key_id`` and ``secret_access_key``: the held key
        when it is an active key of the user, else a new one; every other key
        and every other inline policy of the user is deleted.
    """
    if not _exists(session, user):
        session.write("CreateUser", UserName=user)
        if session.check_mode:
            return {"minted": True, "access_key_id": None, "secret_access_key": None}
    _policy(session, user, name, policy)
    return _key(session, user, held)


def absent(session: Session, user: str) -> None:
    """Args:
    session: the IAM session of the admin.
    user: the IAM user name.
    """
    if not _exists(session, user):
        return
    for member in _members(session, "ListAccessKeys", user, "AccessKeyMetadata"):
        key_id = member.findtext("AccessKeyId")
        session.write("DeleteAccessKey", UserName=user, AccessKeyId=key_id)
    for member in _members(session, "ListUserPolicies", user, "PolicyNames"):
        session.write("DeleteUserPolicy", UserName=user, PolicyName=member.text)
    session.write("DeleteUser", UserName=user)


def main():
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_if=REQUIRED_IF,
        supports_check_mode=True,
    )
    params = module.params
    session = Session(
        {
            "access_key_id": params["admin_access_key_id"],
            "secret_access_key": params["admin_secret_access_key"],
        },
        module.check_mode,
    )
    result: dict = {}
    try:
        if params["state"] == "present":
            result = present(
                session,
                params["user"],
                params["policy_name"],
                params["policy"],
                params["held_access_key_id"],
            )
        else:
            absent(session, params["user"])
    except (AwsError, OSError) as error:
        module.fail_json(
            msg=f"semaphore_route53_user: {params['state']} of {params['user']}: {error}",
            changes=session.changes,
        )
    module.exit_json(changed=bool(session.changes), changes=session.changes, **result)


if __name__ == "__main__":
    main()
