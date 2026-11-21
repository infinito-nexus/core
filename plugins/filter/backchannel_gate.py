from ansible.errors import AnsibleFilterError
from ansible.module_utils.parsing.convert_bool import boolean

from utils.roles.applications.config import get

GATE_FLAG = "services.sso.oidc.backchannel_logout_gate"


def logout_gate_apps(applications, group_names):
    """Return the deployed applications whose receivers sit behind the logout gate.

    Args:
        applications: the ``lookup('applications')`` map, application id -> config.
        group_names: the application ids deployed on this host.

    Returns:
        The sorted ids of the deployed applications that set
        ``services.sso.oidc.backchannel_logout_gate``.
    """
    try:
        return sorted(
            app_id
            for app_id in applications
            if app_id in group_names
            and boolean(
                get(applications, app_id, GATE_FLAG, strict=False, default=False)
            )
        )
    except Exception as error:
        raise AnsibleFilterError(f"logout_gate_apps filter error: {error}") from error


class FilterModule:
    def filters(self):
        return {"logout_gate_apps": logout_gate_apps}
