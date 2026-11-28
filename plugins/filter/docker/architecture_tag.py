from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.docker.image.architecture_tags import architecture_tag


def docker_architecture_tag(version, architecture, rewrites) -> str:
    """
    Args:
        version: the service's pinned ``version``.
        architecture: the OCI architecture of the node that pulls the image.
        rewrites: the service's ``architecture_tags``; empty or None when
            every architecture pulls ``version``.

    Returns:
        The tag *architecture* pulls, derived from *version*.

    Raises:
        AnsibleFilterError: the rewrite is malformed or *version* lacks the
            prefix it rewrites.
    """
    try:
        return architecture_tag(str(version), str(architecture), rewrites)
    except (TypeError, ValueError) as error:
        raise AnsibleFilterError(f"docker_architecture_tag: {error}") from None


class FilterModule:
    def filters(self):
        return {"docker_architecture_tag": docker_architecture_tag}
