from ansible.errors import AnsibleFilterError


def get_primary_domain(domains, application_id):
    """
    Return the primary domain for application_id from the domains mapping:
      - If value is a string, return it.
      - If value is a dict, return its first value.
      - If value is a list, return its first element.
      - Otherwise, raise an error.
    """
    if not isinstance(domains, dict):
        raise AnsibleFilterError(
            f"'domains' must be a dict, got {type(domains).__name__}"
        )

    if application_id not in domains:
        raise AnsibleFilterError(
            f"application_id '{application_id}' not found in domains mapping"
        )

    val = domains[application_id]

    if isinstance(val, str):
        if not val:
            raise AnsibleFilterError(f"domains['{application_id}'] is an empty string")
        return val

    if isinstance(val, dict):
        try:
            first_val = next(iter(val.values()))
        except StopIteration:
            raise AnsibleFilterError(
                f"domains['{application_id}'] dict is empty"
            ) from None
        if not isinstance(first_val, str) or not first_val:
            raise AnsibleFilterError(
                f"first value of domains['{application_id}'] must be a non-empty string, got {first_val!r}"
            )
        return first_val

    if isinstance(val, list):
        if not val:
            raise AnsibleFilterError(f"domains['{application_id}'] list is empty")
        first = val[0]
        if not isinstance(first, str) or not first:
            raise AnsibleFilterError(
                f"first element of domains['{application_id}'] must be a non-empty string, got {first!r}"
            )
        return first

    raise AnsibleFilterError(
        f"domains['{application_id}'] has unsupported type {type(val).__name__}, must be str, dict or list"
    )


def get_domain(domains, application_id):
    return get_primary_domain(domains, application_id)
