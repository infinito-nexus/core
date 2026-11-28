from __future__ import annotations

from utils.digests import COMMIT

REF_KINDS = ("tag", "branch", "commit")
REF_KIND_KEY = "ref_kind"


def git_refspec(ref: str, kind: str) -> str:
    """Return the refspec of a shallow clone of a pinned git ref.

    Args:
        ref: the pinned git ref.
        kind: one of ``REF_KINDS``, the ``ref_kind`` the entity declares.

    Returns:
        ``+refs/tags/<ref>:refs/tags/<ref>`` for a tag, ``""`` for a branch,
        and the commit itself for a commit, which git fetches by its full
        40-hex SHA only.

    Raises:
        ValueError: ``kind`` is not one of ``REF_KINDS``, or a ``commit`` ref
            is not a full 40-hex SHA.
    """
    if kind not in REF_KINDS:
        raise ValueError(
            f"{REF_KIND_KEY} {kind!r} of git ref {ref!r} is not one of "
            + ", ".join(REF_KINDS)
        )
    if kind == "branch":
        return ""
    if kind == "commit":
        if COMMIT.fullmatch(ref) is None:
            raise ValueError(
                f"{REF_KIND_KEY} 'commit' needs a full 40-hex SHA, got {ref!r}"
            )
        return ref
    return f"+refs/tags/{ref}:refs/tags/{ref}"
