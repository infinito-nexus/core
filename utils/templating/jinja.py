#
# Strict Jinja2 renderer for values that may contain Jinja markers.
#
# Why:
# - In some Ansible lookup evaluation contexts, templating can leave "{{ ... }}"
#   untouched without failing.
# - We want hard-fail semantics to avoid leaking Jinja into generated configs.
#
# Additionally:
# - Support nested Jinja-in-vars by rendering multiple passes with a depth limit.
#   Example:
#     CA_TRUST.cert_host = "{{ CA_ROOT.cert_host }}"
#     CA_ROOT.cert_host  = "/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt"
#   We want the final result without any "{{ ... }}" left.

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError


def as_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def looks_like_jinja(s: str) -> bool:
    return ("{{" in s) or ("{%" in s)


def build_render_context(variables: dict[str, Any]) -> tuple[dict, str]:
    """
    Build a robust context for rendering Jinja-in-strings.

    We intentionally do NOT rely on Ansible's Templar here because in some
    lookup evaluation contexts it can silently keep Jinja markers untouched.

    Context priority:
      1) variables dict
      2) hostvars[inventory_hostname] overlays variables (wins on conflicts)
    """
    ctx: dict = {}
    if isinstance(variables, dict):
        ctx.update(variables)

    inv_host = as_str(variables.get("inventory_hostname", "")).strip()

    hostvars = variables.get("hostvars") if isinstance(variables, dict) else None
    if inv_host and isinstance(hostvars, dict):
        hv = hostvars.get(inv_host)
        if isinstance(hv, dict):
            ctx.update(hv)

    return ctx, inv_host


def _jinja_env():
    try:
        from jinja2 import Environment, StrictUndefined, select_autoescape
    except Exception as exc:
        raise AnsibleError(f"jinja_strict: cannot import jinja2. Error: {exc}") from exc
    return Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_jinja2_strict_once(
    raw: str, *, ctx: dict, inv_host: str, var_name: str, err_prefix: str
) -> str:
    """
    Render ONE pass using plain Jinja2 with StrictUndefined.
    Missing vars fail hard.
    """
    if not looks_like_jinja(raw):
        return raw

    env = _jinja_env()
    try:
        rendered = env.from_string(raw).render(ctx)
    except Exception as exc:
        raise AnsibleError(
            f"{err_prefix}: failed to render {var_name} via strict Jinja2. "
            f"inventory_hostname='{inv_host}'. Raw: {raw}. Error: {exc}"
        ) from exc

    return as_str(rendered)


def render_jinja2_strict_recursive(
    raw: str,
    *,
    ctx: dict,
    inv_host: str,
    var_name: str,
    err_prefix: str,
    max_passes: int = 5,
) -> str:
    """
    Render using strict Jinja2 repeatedly until:
      - no Jinja markers remain, OR
      - output stops changing, OR
      - max_passes is reached

    Hard-fail if markers remain after max_passes / stabilization.
    """
    if not looks_like_jinja(raw):
        return raw

    current = raw
    for i in range(max_passes):
        rendered = render_jinja2_strict_once(
            current,
            ctx=ctx,
            inv_host=inv_host,
            var_name=var_name,
            err_prefix=err_prefix,
        )

        # Stable and no markers -> done
        if not looks_like_jinja(rendered):
            return rendered

        # If it didn't change but still has markers -> cannot resolve further
        if rendered == current:
            raise AnsibleError(
                f"{err_prefix}: {var_name} did not fully expand (still contains Jinja markers) "
                f"after pass {i + 1}/{max_passes}. inventory_hostname='{inv_host}'. "
                f"Value: {rendered}."
            )

        current = rendered

    # max passes reached and still markers
    raise AnsibleError(
        f"{err_prefix}: {var_name} did not fully expand (still contains Jinja markers) "
        f"after {max_passes} passes. inventory_hostname='{inv_host}'. "
        f"Raw: {raw} | Rendered: {current}."
    )


def render_strict(
    value: Any,
    *,
    variables: dict[str, Any],
    var_name: str,
    err_prefix: str,
    max_passes: int = 5,
) -> str:
    """
    Convenience wrapper:
    - converts to string
    - if Jinja markers exist => render via strict Jinja2 using a robust context
      (recursive with depth limit)
    - hard-fail if Jinja markers remain
    """
    raw = as_str(value)
    if not raw:
        return raw
    if not looks_like_jinja(raw):
        return raw

    ctx, inv_host = build_render_context(variables)
    rendered = render_jinja2_strict_recursive(
        raw,
        ctx=ctx,
        inv_host=inv_host,
        var_name=var_name,
        err_prefix=err_prefix,
        max_passes=max_passes,
    )

    if looks_like_jinja(rendered):
        # Shouldn't happen (recursive renderer already fails), but keep belt+suspenders.
        raise AnsibleError(
            f"{err_prefix}: {var_name} did not fully expand (still contains Jinja markers). "
            f"inventory_hostname='{inv_host}'. Raw: {raw} | Rendered: {rendered}."
        )

    return rendered
