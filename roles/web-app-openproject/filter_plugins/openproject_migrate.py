from ansible.errors import AnsibleFilterError


def openproject_migrations_pending(stamp, image):
    """Tell whether ``db:migrate`` must run in the web container.

    Args:
        stamp: the image id on ``schema_migrations``, written only after
            ``db:migrate`` succeeded; empty when no run succeeded yet.
        image: the image id of the running web container.

    Returns:
        ``False`` only when ``stamp`` names ``image``.

    Raises:
        AnsibleFilterError: ``image`` is empty, which would let an empty
            stamp pass for current.
    """
    current = str(image).strip()
    if not current:
        raise AnsibleFilterError(
            "openproject_migrations_pending: the web container reported no image id"
        )
    return str(stamp).strip() != current


class FilterModule:
    def filters(self):
        return {"openproject_migrations_pending": openproject_migrations_pending}
