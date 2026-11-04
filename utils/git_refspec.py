from __future__ import annotations

REF_KINDS = ("tag", "branch")
REF_KIND_KEY = "ref_kind"


def git_refspec(ref: str, kind: str) -> str:
    """Return the refspec of a shallow clone of a pinned git ref.

    Args:
        ref: the pinned git ref.
        kind: one of ``REF_KINDS``, the ``ref_kind`` the entity declares.

    Returns:
        ``+refs/tags/<ref>:refs/tags/<ref>`` for a tag, ``""`` for a branch.

    Raises:
        ValueError: ``kind`` is not one of ``REF_KINDS``.
    """
    if kind not in REF_KINDS:
        raise ValueError(
            f"{REF_KIND_KEY} {kind!r} of git ref {ref!r} is not one of "
            + ", ".join(REF_KINDS)
        )
    if kind == "branch":
        return ""
    return f"+refs/tags/{ref}:refs/tags/{ref}"
