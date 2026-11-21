"""Negative control: a spec is only proven to guard its input when breaking
that input turns the spec red and restoring it turns the spec green again. One
half alone proves nothing, so the control passes only when both halves held.
"""

from __future__ import annotations


def control_result(before_red: bool, after_green: bool) -> bool:
    """Return whether the negative control passed: the broken input turned the
    spec red and the restored input turned it green.

    Args:
        before_red: whether the spec failed while the guarded input was broken.
        after_green: whether the spec passed once the input was restored.
    """
    return before_red and after_green
