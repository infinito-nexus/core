from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.git_refspec import git_refspec as _git_refspec


def git_refspec(ref: str, kind: str) -> str:
    """Return the refspec of a shallow clone of a pinned git ref.

    Args:
        ref: the pinned git ref.
        kind: ``tag``, ``branch`` or ``commit``, the ``ref_kind`` the entity
            declares.

    Returns:
        ``+refs/tags/<ref>:refs/tags/<ref>`` for a tag, ``""`` for a branch,
        the full SHA itself for a commit.
    """
    try:
        return _git_refspec(str(ref), str(kind))
    except ValueError as exc:
        raise AnsibleFilterError(f"git_refspec: {exc}") from exc


class FilterModule:
    def filters(self):
        return {"git_refspec": git_refspec}
