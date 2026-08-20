from __future__ import annotations

import contextlib
import os
import posixpath
import re
from typing import Any

from ansible.errors import AnsibleError

from utils.manager.value_generator import ValueGenerator
from utils.templating.expr import (
    find_top_level_op,
    is_paren_wrapped,
    split_list_items,
    split_top_level,
)

try:
    from ansible._internal._datatag._tags import TrustedAsTemplate
except Exception:
    TrustedAsTemplate = None


def _trust_as_template(s: str) -> Any:
    """Tag a string as trusted for Jinja templating in Ansible 2.19+.

    Ansible's templar refuses to render strings that aren't tagged via
    TrustedAsTemplate. YAML loaded directly with yaml.safe_load lacks this
    tag, so embedded {{ ... }} returns unchanged. Tagging restores rendering.
    """
    if TrustedAsTemplate is None or not isinstance(s, str):
        return s
    try:
        return TrustedAsTemplate().tag(s)
    except Exception:
        return s


# Match the "lookup('env','NAME')" head (without caring about trailing filters)
_RE_LOOKUP_ENV_HEAD = re.compile(
    r"""^lookup\(\s*['"]env['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*""",
    re.IGNORECASE,
)

_RE_ANY_LOOKUP = re.compile(r"""\blookup\s*\(""", re.IGNORECASE)

_RE_VARPATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")
_RE_INT_LITERAL = re.compile(r"^-?\d+$")
_RE_FLOAT_LITERAL = re.compile(r"^-?\d+\.\d+$")
_RE_JINJA_BLOCK = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)


def _eval_list_literal(head: str, variables: dict) -> list[str]:
    """
    Evaluate a minimal Jinja list literal like:
      [ DIR_BIN, 'ca-inject' ]

    Items supported:
      - quoted strings ('x' / "x")
      - varpaths (FOO / FOO.bar)

    This is intentionally minimal and safe for fallback rendering.
    """
    h = head.strip()
    if not (h.startswith("[") and h.endswith("]")):
        raise ValueError("not a list literal")

    inner = h[1:-1].strip()
    if not inner:
        return []

    out: list[str] = []
    for tok in split_list_items(inner):
        t = tok.strip()
        if not t:
            continue

        # Quoted string
        if t.startswith(("'", '"')) and t.endswith(t[0]) and len(t) >= 2:
            out.append(t[1:-1])
            continue

        # Variable path
        if not _RE_VARPATH.match(t):
            # Keep the error message consistent with the old behavior
            raise ValueError(f"unsupported expression: {head}")

        try:
            v = _get_by_path(variables, t)
        except KeyError:
            v = None

        out.append("" if v is None else str(v))

    return out


def _get_by_path(variables: dict, path: str) -> Any:
    cur: Any = variables
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def _apply_filter(value: Any, filt: str) -> Any:
    f = filt.strip()

    if f == "lower":
        return str(value).lower()

    if f == "upper":
        return str(value).upper()

    # Support the common Ansible/Jinja pattern:
    #   {{ [ DIR_BIN, 'ca-inject' ] | path_join }}
    # Only for list/tuple inputs; otherwise no-op.
    if f == "path_join":
        if not isinstance(value, (list, tuple)):
            return value
        parts = [str(x) for x in value if str(x) != ""]
        return posixpath.join(*parts) if parts else ""

    if f == "strong_password":
        try:
            length = int(value)
        except (TypeError, ValueError):
            length = 32
        return ValueGenerator().generate_strong_password(length)

    # default('x', true) -> treat None/"" as default
    if f.startswith("default(") and f.endswith(")"):
        inner = f[len("default(") : -1].strip()

        default_val: Any = ""
        if inner.startswith(("'", '"')):
            q = inner[0]
            end = inner.find(q, 1)
            default_val = inner[1:end] if end != -1 else ""
        else:
            default_val = inner.split(",", 1)[0].strip()

        if value is None:
            return default_val
        if str(value) == "":
            return default_val
        return value

    # Unknown filter -> no-op
    return value


def _eval_condition(cond: str, variables: dict) -> bool:
    """Evaluate a minimal boolean condition: ``A == B`` / ``A != B`` / truthy."""
    for op, test in (("==", str.__eq__), ("!=", str.__ne__)):
        idx = find_top_level_op(cond, op)
        if idx != -1:
            left = _fallback_eval_expr(cond[:idx], variables)
            right = _fallback_eval_expr(cond[idx + len(op) :], variables)
            return bool(test(left, right))
    val = _fallback_eval_expr(cond, variables)
    return val not in ("", "False", "false", "0", "None")


def _fallback_eval_expr(expr: str, variables: dict) -> str:
    """
    Evaluate a single Jinja expression (no surrounding {{ }}).

    Supported subset (SAFE fallback only):
      - lookup('env','NAME')
      - VAR / VAR.path
      - list literal: [ VAR, 'literal', ... ]
      - string concatenation: 'a' ~ VAR ~ 'b'
      - inline conditional: A if COND else B  (COND: X == 'y' / X != 'y')
      - filters: | lower, | upper, | default('x', true), | path_join

    Any other lookup(...) must NOT be handled here.
    """
    expr = expr.strip()

    # Inline conditional: A if COND else B
    if_idx = find_top_level_op(expr, " if ")
    else_idx = find_top_level_op(expr, " else ")
    if if_idx != -1 and else_idx != -1 and if_idx < else_idx:
        a = expr[:if_idx]
        cond = expr[if_idx + len(" if ") : else_idx]
        b = expr[else_idx + len(" else ") :]
        chosen = a if _eval_condition(cond, variables) else b
        return _fallback_eval_expr(chosen, variables)

    # Fully parenthesised expression
    if is_paren_wrapped(expr):
        return _fallback_eval_expr(expr[1:-1], variables)

    # String concatenation with ~
    tilde_parts = split_top_level(expr, "~")
    if len(tilde_parts) > 1:
        return "".join(_fallback_eval_expr(p, variables) for p in tilde_parts)

    # Bare string literal
    if len(expr) >= 2 and expr[0] in "'\"" and expr[-1] == expr[0]:
        return expr[1:-1]

    parts = [p.strip() for p in expr.split("|")]
    head = parts[0].strip()

    m = _RE_LOOKUP_ENV_HEAD.match(head)
    if m:
        key = m.group(1)
        val: Any = os.environ.get(key)
        if val is None:
            # Convenience: match your tests / typical usage (DOMAIN vs domain)
            val = os.environ.get(key.lower(), os.environ.get(key.upper()))
    # Allow minimal list literals (needed for patterns like: [ DIR_BIN, 'x' ] | path_join)
    elif head.startswith("[") and head.endswith("]"):
        val = _eval_list_literal(head, variables)
    elif _RE_INT_LITERAL.match(head):
        val = int(head)
    elif _RE_FLOAT_LITERAL.match(head):
        val = float(head)
    else:
        if not _RE_VARPATH.match(head):
            raise ValueError(f"unsupported expression: {head}")
        try:
            val = _get_by_path(variables, head)
        except KeyError:
            val = None

    for filt in parts[1:]:
        val = _apply_filter(val, filt)

    return "" if val is None else str(val)


def _fallback_render_embedded(s: str, variables: dict) -> str:
    def repl(m: re.Match) -> str:
        expr = (m.group(1) or "").strip()
        return _fallback_eval_expr(expr, variables)

    return _RE_JINJA_BLOCK.sub(repl, s)


def _contains_non_env_lookup(s: str) -> bool:
    """
    True if any embedded {{ ... }} contains lookup(...) that is NOT lookup('env', ...).

    IMPORTANT:
    - Allow lookup('env', ...) even when followed by filters, e.g.
      {{ lookup('env','domain') | default('x', true) }}
    """
    for m in _RE_JINJA_BLOCK.finditer(s):
        expr = (m.group(1) or "").strip()
        if _RE_ANY_LOOKUP.search(expr):
            # If the expression starts with lookup('env', ...) (filters allowed), it's safe
            if _RE_LOOKUP_ENV_HEAD.match(expr):
                continue
            return True
    return False


def _set_templar_var(templar: Any, name: str, value: Any) -> tuple[bool, Any]:
    """
    Best-effort setter for templar flags across Ansible versions.
    Returns (changed, previous_value).
    """
    if templar is None or not hasattr(templar, name):
        return False, None
    try:
        prev = getattr(templar, name)
        setattr(templar, name, value)
    except Exception:
        return False, None
    return True, prev


def _templar_render_preserve_type(templar: Any, s: str, variables: dict) -> Any:
    """
    Type-preserving render for the case where the entire string is a
    single Jinja expression. Unlike `_templar_render_best_effort` (which
    forces ``str(rendered)``), this returns templar's native output —
    so a list/dict-returning ``lookup(...)`` keeps its type.

    Caller MUST pre-check the input shape; this function does no shape
    detection itself. Returns ``None`` if templar is unavailable or
    raises during render — caller is expected to fall back to the
    string-coerced path in that case.
    """
    if templar is None:
        return None

    disable_changed_1, prev_disable_1 = _set_templar_var(
        templar, "disable_lookups", False
    )
    disable_changed_2, prev_disable_2 = _set_templar_var(
        templar, "_disable_lookups", False
    )

    prev_avail: Any | None = None
    if hasattr(templar, "available_variables"):
        try:
            prev_avail = templar.available_variables
            merged_avail: dict = dict(prev_avail) if prev_avail else {}
            if variables:
                merged_avail.update(variables)
            templar.available_variables = merged_avail
        except Exception:
            prev_avail = None

    rendered: Any = None
    try:
        try:
            rendered = templar.template(_trust_as_template(s), fail_on_undefined=True)
        except TypeError:
            rendered = templar.template(_trust_as_template(s))
        except Exception:
            rendered = None
    finally:
        if prev_avail is not None and hasattr(templar, "available_variables"):
            with contextlib.suppress(Exception):
                templar.available_variables = prev_avail
        if disable_changed_2:
            with contextlib.suppress(Exception):
                templar._disable_lookups = prev_disable_2
        if disable_changed_1:
            with contextlib.suppress(Exception):
                templar.disable_lookups = prev_disable_1

    return rendered


def _templar_render_best_effort(templar: Any, s: str, variables: dict) -> str:
    """
    Render with Ansible templar across versions.

    Policy:
    - Always try templar first (so ALL lookup(...) can be evaluated properly).
    - If templar returns unchanged while Jinja exists:
        - If string contains non-env lookup(...): DO NOT fallback (leave as-is)
        - Else: fallback is allowed (env + varpaths + simple filters)
    """
    if templar is None:
        return _fallback_render_embedded(s, variables)

    prev_avail: Any | None = None

    # Temporarily force lookups ON (different Ansible versions use different flags)
    disable_changed_1, prev_disable_1 = _set_templar_var(
        templar, "disable_lookups", False
    )
    disable_changed_2, prev_disable_2 = _set_templar_var(
        templar, "_disable_lookups", False
    )

    if hasattr(templar, "available_variables"):
        try:
            prev_avail = templar.available_variables
            # Merge additively so templar keeps access to ansible_facts /
            # hostvars etc. from prev_avail while our caller-supplied keys
            # (e.g. _INFINITO_APPLICATIONS_RAW) are layered on top. Replacing
            # wholesale drops fact keys that aren't rematerialized by
            # dict(variables) in the caller.
            merged_avail: dict = dict(prev_avail) if prev_avail else {}
            if variables:
                merged_avail.update(variables)
            templar.available_variables = merged_avail
        except Exception:
            prev_avail = None

    rendered: Any = s
    trusted_input = _trust_as_template(s)
    try:
        try:
            rendered = templar.template(trusted_input, fail_on_undefined=True)
        except TypeError:
            rendered = templar.template(trusted_input)
        except Exception:
            # If templar is present but fails unexpectedly, fall back to safe subset below.
            rendered = s
    finally:
        # Best-effort cleanup: failure to restore any of the templar
        # attributes is intentionally ignored.
        if prev_avail is not None and hasattr(templar, "available_variables"):
            with contextlib.suppress(Exception):
                templar.available_variables = prev_avail

        if disable_changed_2:
            with contextlib.suppress(Exception):
                templar._disable_lookups = prev_disable_2
        if disable_changed_1:
            with contextlib.suppress(Exception):
                templar.disable_lookups = prev_disable_1

    # Normalize to string (templar may return None)
    out_s = "" if rendered is None else str(rendered)

    # If templar didn't change anything while Jinja exists:
    if out_s.strip() == s.strip() and ("{{" in s or "{%" in s):
        # If it contains any non-env lookup(...), fallback would be wrong.
        if _contains_non_env_lookup(s):
            return out_s

        # Otherwise safe to attempt limited fallback for embedded patterns.
        return _fallback_render_embedded(s, variables)

    return out_s


def render_ansible_strict(
    *,
    templar: Any,
    raw: Any,
    var_name: str,
    err_prefix: str,
    variables: dict,
    max_rounds: int = 6,
) -> str:
    """
    Strict rendering helper for lookup/filter plugins.

    - Renders via Ansible templar when possible (lookup(), filters, vars).
    - Automatic fallback is enabled for a SAFE subset (env lookup + varpaths + simple filters)
      only when templar can't/won't render and NO non-env lookup(...) is present.
    - Re-renders multiple rounds because intermediate results can still contain Jinja.
    - Hard-fails if output is empty or still contains unresolved Jinja markers.
    """
    if raw is None:
        raise AnsibleError(f"{err_prefix}: {var_name} resolved to None")

    s = str(raw)

    out = s
    for _ in range(max_rounds):
        if ("{{" not in out) and ("{%" not in out):
            break
        out2 = _templar_render_best_effort(templar, out, variables)
        if out2 == out:
            break
        out = out2

    out = "" if out is None else str(out).strip()
    if not out:
        raise AnsibleError(
            f"{err_prefix}: {var_name} rendered to empty string. Raw: {s}"
        )

    if ("{{" in out) or ("{%" in out):
        raise AnsibleError(
            f"{err_prefix}: {var_name} still contains unresolved Jinja. Rendered: {out}. Raw: {s}"
        )

    return out
