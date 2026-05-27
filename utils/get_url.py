from ansible.errors import AnsibleFilterError

from utils.domains.primary_domain import get_domain


def get_url(domains, application_id, protocol):
    if not isinstance(protocol, str):
        raise AnsibleFilterError("Protocol must be a string")
    return f"{protocol}://{get_domain(domains, application_id)}"
