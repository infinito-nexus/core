"""Lint guard: an end-of-life service stays off, and only an EOL role binds it.

A role whose primary entity carries ``lifecycle: eol`` receives no upstream
fixes. Its implementation stays in the tree so an existing deployment keeps its
migration path, but nothing may switch it back on: the lifecycle envelope
``INFINITO_LIFECYCLES`` (``default.env:245``) drops it from every CI round under
the default envelope, so a consumer that enables it binds a partner no test ever
deploys, and the dependency surfaces first on a production host as an
unreachable integration. An explicit ``lifecycles: eol`` workflow dispatch
(``.github/workflows/entry-manual-steer.yml``) deploys the role standalone,
which is the one round it is exercised in; the stored literals keep every
partner unbound even there. The policy this file enforces lives at
``docs/contributing/design/role/services/lifecycle.md``.

Five assertions, one per re-entry point plus two over the exemption ledger:

* ``meta/services.yml``: the EOL role's OWN primary block MUST store
  ``enabled`` as a literal ``false``, and every other role's block for an EOL
  key MUST keep ``enabled`` literally ``false``. A dynamic
  ``"{{ 'web-app-<x>' in group_names }}"`` flag is exactly a re-entry point: it
  turns true the moment the EOL role joins an inventory.
* ``meta/variants.yml``: no variant of any role may pin ``enabled`` truthy,
  including a variant of the EOL role itself, under ``services:`` or under
  ``addons:`` - the latter reaches the same partner through the pinned addon's
  ``bridges:`` list, and ``roles/web-app-matrix/meta/variants.yml`` carries a
  live ``addons:`` block.
* ``meta/addons/*.yml``: an addon whose ``bridges:`` list names an EOL key MUST
  gate on a literal ``false`` or on the exact reference
  ``{{ lookup('config', '<own-role>', 'services.<eol-key>.enabled') | bool }}``,
  matched anchored over the whole expression, with either quote character and
  optional whitespace after ``lookup(`` and around its commas. Only an exact
  match contains the gate: a substring test passes ``{{ not lookup(…) }}`` and
  ``{{ lookup(…) or true }}``, both of which render TRUE. An addon with no
  ``bridges:`` integrates an external SaaS provider through
  ``lookup('api_enabled', …)`` (credentials from
  ``group_vars/all/18_api.yml``), not the in-repo role, and is out of scope.
  ``test_addons_schema`` is what holds ``bridges`` to a non-empty list of
  strings, and this walk deliberately does not depend on it: that lint is
  suppressible from an addon's head with ``# nocheck: addon-schema``, so a
  scalar ``bridges: jira`` behind one marker would leave this rule with nothing
  bound while the loader still resolves the addon as enabled.
  :func:`_addon_bridges` therefore fails closed - a ``bridges`` key that is
  present but off-shape binds every string the value holds at any depth.
* the exemption ledger: ``exempt_eol_roles`` MUST stay inside
  ``WHOLE_RULE_EXEMPTIONS``, because that marker drops every consumer of a
  service in one move, and no whole-rule marker may be bare.

An addon's enable state is resolved the way the loader resolves it
(``utils.cache.applications._normalize_addons``): a missing ``enabled`` falls
back to ``required``, which itself defaults to ``false``. An optional addon
that declares no gate is therefore already contained and is not an offence.

The key set is derived the way the registry derives it: the primary entity name,
every ``provides`` entry (string or list) and every ``canonical`` alias that
normalises to the entity name (``registry.py:132-150``). Twelve roles declare
``provides``, so deriving from the entity name alone would let a renamed
consumer-facing key escape. The entity name is kept unconditionally rather than
read back out of the registry: ``is_provider`` needs ``shared``/``provides``/an
alias, so ``web-app-phpldapadmin`` - whose primary carries no ``shared`` key -
is absent from the registry entirely, and a registry-derived set would cover it
vacuously.

A role that is itself EOL is exempt for FOREIGN keys only: one dead integration
may name another, and both leave together. Its own key is never exempt, or the
app re-enables itself.

``test_clearnet_role_forbids_variant_tor`` is the structural sibling: same
two-sided walk, a different marker on the bound role.

Why ``shared`` is NOT checked
=============================

``shared: true`` on the EOL role's own primary is deliberately retained, and
this lint is what makes that safe. ``shared`` is the key that registers the
entity as a provider (``registry.py:142``), and the registry is what
``expand_service_tokens`` uses to accept both spellings of an operator's
service reference. Measured on a throwaway tree materialised from HEAD and from
the working tree: with ``shared: false`` on ``web-app-minio``'s primary,
``expand_service_tokens(['web-app-minio'])`` returns ``['web-app-minio']``
verbatim instead of ``['minio']``, so ``disable=web-app-minio`` silently
matches nothing, the ``disable``-vs-inventory guard in
``cli/administration/inventory/provision/services_disabler.py`` stops reporting
that a disabled service's provider is still in the inventory, and the role drops
out of the sys-service-loader preload order into the ordinary app pass.
Withdrawing the provider registration therefore costs the ``disable=`` surface
and the deploy order without buying containment: ``--include`` does not route
through ``expand_service_tokens`` at all. The literal ``enabled: false`` plus
these four assertions are the control that keeps a consumer from binding the
dead app.

Only ``minio`` regressed, measured the same way: ``web-app-jira`` and
``web-app-confluence`` carried no ``shared`` on their primary at all before
this change, so ``expand_service_tokens(['web-app-jira'])`` already returned
the token verbatim and ``disable=web-app-jira`` was already a no-op. Their
``shared: true`` is new registration, not a restoration.
``web-app-phpldapadmin`` still declares none and stays out of the registry,
which is why the key set below keeps the entity name unconditionally.

Why no variant pin backs the literal
====================================

The variant pins that used to hold these keys ``false`` were removed; the single
literal plus these assertions are the compensating control. The pins were not
cost-free. Measured with ``cli.meta.roles.applications.ressources`` on a
throwaway tree: regressing ``web-app-mattermost``'s base ``jira`` flag to the
``in group_names`` form makes variant 2 resolve the EOL app again, at +4.0 GB
mem_reservation, +6.0 GB mem_limit, +1.027 GB min_storage and +2048 pids over
the live 42.12 GB / 83.89 GB / 55.18 GB / 33024 - a dependency the variant-2 pin
had previously contained. The literal is what closes it now, which is why the
first assertion treats a missing or non-literal flag as an offence rather than a
style nit.

Measured reduction of the removal itself (same tool, ``mem_reservation``, staged
index to working tree) - a later variant-budget change has to be able to tell
this drop apart from a regression:

* ``web-app-gitlab`` variant 0 and variant 2: -4.0 GB each (59.80 -> 55.80 GB)
* ``web-app-gitlab`` variant 1: -10.0 GB (65.30 -> 55.30 GB)
* ``web-app-matrix`` variant 1: -3.0 GB (45.98 -> 42.98 GB)
* ``web-app-mattermost`` variants 0 and 1: -10.0 GB each (68.08 -> 58.08 GB)
* all four EOL roles: unchanged

``web-app-gitlab`` variant 0 and variant 2 close a depth-4 transitive path
(gitlab to mattermost to jira) that only became reachable statically because
mattermost's base flag was dynamic.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: eol-dependency`` on the offending ``enabled:`` line, or on the
  nearest non-blank line above it when that is a COMMENT line, in a consumer's
  ``meta/services.yml``, ``meta/variants.yml`` or ``meta/addons/<id>.yml``, for
  a case that is sound only there. The line above is accepted only when it is a
  comment or when its
  indent is strictly smaller than the judged line's: a marker carrying a reason
  on a nested ``enabled:`` inside a ``modes:`` sub-block, or on the sibling
  ``shared:`` that happens to be the nearest non-blank line above, would
  otherwise silence the top-level flag it sits beside. Inside a
  ``meta/variants.yml`` the marker must also resolve INSIDE the span of the
  variant being judged, so a marker parked in the neighbouring variant cannot
  reach this one.
* ``# nocheck: eol-dependency-provider`` in the HEAD of the EOL role's own
  ``meta/services.yml`` (the first 30 lines, the same placement ``file-size``
  uses) drops that role from the EOL set, which exempts every consumer in the
  repository at once: an EOL entity that still backs a live surface is a
  provider the rule has no claim on. The scope has its own rule key precisely
  because it cannot be read off a position - a trailing
  ``# nocheck: eol-dependency`` on a flag that happens to sit in the first 30
  lines would otherwise claim the repository-wide scope by an accident of line
  numbering - and :meth:`test_no_eol_role_exempts_every_consumer` keeps the
  exemption red until it is recorded in ``WHOLE_RULE_EXEMPTIONS``.

Every marker of either key MUST carry a reason naming why the dependency
survives the upstream's end of life; a bare marker is rejected, the way
``onion-flag`` rejects one. A bare whole-rule marker grants nothing and is
reported by :meth:`test_no_whole_rule_marker_is_bare`, so the strongest marker
is held to the same bar as the weakest.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
)
from utils.roles.meta_lookup import get_role_lifecycle

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
_RULE = "eol-dependency"
_PROVIDER_RULE = "eol-dependency-provider"
_EOL = "eol"
_FLAG = "enabled"
_MIN_REASON_CHARS = 10
_HEAD_LINES = 30

WHOLE_RULE_EXEMPTIONS: frozenset[str] = frozenset()
"""EOL roles whose repository-wide exemption has been reviewed and recorded."""

_MARKER_RE = re.compile(
    r"(?:noqa|nocheck)\s*:\s*"
    r"(?:[a-z0-9][a-z0-9\-]*)(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*(.*)$",
    re.IGNORECASE,
)
_COMMENT_LINE_RE = re.compile(r"^\s*#")
_LIST_ENTRY_RE = re.compile(r"^-(?:\s|$)")


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None


def _load_mapping(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    return data if isinstance(data, dict) else {}


def _lines(path: Path) -> list[str]:
    return read_text(str(path)).splitlines() if path.is_file() else []


def _role_dirs() -> list[Path]:
    return sorted(p for p in ROLES_DIR.iterdir() if p.is_dir())


def _eol_role_dirs() -> list[Path]:
    return [
        role_dir for role_dir in _role_dirs() if get_role_lifecycle(role_dir) == _EOL
    ]


def _marker_reason(line: str) -> str:
    """The text a marker line carries after its rule list, ``""`` when bare."""
    match = _MARKER_RE.search(line)
    return match.group(1).strip().lstrip("-:—").strip() if match else ""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _governs_from_above(above: str, judged: str) -> bool:
    """Whether a marker on *above* may govern the construct on *judged*.

    Args:
        above: the nearest non-blank line above the construct.
        judged: the line the construct sits on.

    Returns:
        True for a comment line, or for a data line that opens a shallower
        nesting level. A sibling (``shared:`` beside ``enabled:``) or a deeper
        line (an ``enabled:`` inside a ``modes:`` sub-block) is rejected: it is
        a construct of its own, and a marker written for it would otherwise
        silence the flag that happens to follow it.
    """
    return bool(_COMMENT_LINE_RE.match(above)) or _indent(above) < _indent(judged)


def _reason_at(
    lines: Sequence[str], line_no: int, bounds: tuple[int, int] | None = None
) -> str | None:
    """The rule's marker text governing 1-based *line_no*.

    Args:
        lines: the file's lines.
        line_no: the 1-based line the construct sits on.
        bounds: an inclusive 1-based ``(first, last)`` range the marker has to
            resolve inside, e.g. one variant's span. ``None`` leaves the whole
            file open.

    Returns:
        The marker's trailing reason, ``""`` for a bare marker, or ``None`` when
        no marker the placement rules accept carries one.
    """
    if line_no < 1 or line_no > len(lines):
        return None
    candidates = [line_no - 1]
    previous = line_no - 2
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    if previous >= 0 and _governs_from_above(lines[previous], lines[line_no - 1]):
        candidates.append(previous)
    for index in candidates:
        if bounds and not bounds[0] <= index + 1 <= bounds[1]:
            continue
        if not line_has_rule(lines[index], _RULE):
            continue
        return _marker_reason(lines[index])
    return None


def _offence_suffix(
    lines: Sequence[str], line_no: int, bounds: tuple[int, int] | None = None
) -> str | None:
    """Whether the construct at *line_no* is still an offence, and why.

    Args:
        lines: the file's lines.
        line_no: the 1-based line the construct sits on.
        bounds: the inclusive 1-based range a marker has to resolve inside.

    Returns:
        ``None`` when a marker with a reason suppresses it, ``""`` when no
        marker applies, or the clause naming the bare marker.
    """
    reason = _reason_at(lines, line_no, bounds)
    if reason is None:
        return ""
    if len(reason) < _MIN_REASON_CHARS:
        return (
            f"; its '# nocheck: {_RULE}' names no reason why the dependency "
            f"outlives the upstream's end of life"
        )
    return None


def _head_reason(role_dir: Path) -> str | None:
    """The whole-rule marker's reason in the role's own ``meta/services.yml``.

    Args:
        role_dir: the role directory.

    Returns:
        The text after ``# nocheck: eol-dependency-provider`` in the file's
        first 30 lines, ``""`` when the marker is bare, or ``None`` when the
        head carries no such marker.
    """
    for line in _lines(role_dir / ROLE_FILE_META_SERVICES)[:_HEAD_LINES]:
        if line_has_rule(line, _PROVIDER_RULE):
            return _marker_reason(line)
    return None


def exempt_eol_roles() -> list[str]:
    """EOL roles the rule's whole-file marker drops from the EOL set.

    Returns:
        The role ids whose own ``meta/services.yml`` carries
        ``# nocheck: eol-dependency-provider`` WITH a reason in its head, which
        exempts every consumer of that role at once. A bare marker grants
        nothing; :func:`bare_exemption_roles` reports it instead.
    """
    return [
        role_dir.name
        for role_dir in _eol_role_dirs()
        if (reason := _head_reason(role_dir)) is not None
        and len(reason) >= _MIN_REASON_CHARS
    ]


def bare_exemption_roles() -> list[str]:
    """EOL roles whose whole-rule marker names no reason.

    Returns:
        The role ids whose own ``meta/services.yml`` head carries
        ``# nocheck: eol-dependency-provider`` without a reason long enough to
        be one. The exemption is withheld, and the marker is reported so it
        cannot sit in the tree looking like a granted one.
    """
    return [
        role_dir.name
        for role_dir in _eol_role_dirs()
        if (reason := _head_reason(role_dir)) is not None
        and len(reason) < _MIN_REASON_CHARS
    ]


def _alias_keys(services: dict[str, Any], entity: str) -> set[str]:
    """Keys in the role's own file whose ``canonical`` normalises to ``entity``."""
    return {
        str(key)
        for key, entry in services.items()
        if isinstance(entry, dict)
        and isinstance(entry.get("canonical"), str)
        and entry["canonical"].strip() == entity
    }


def _provided_keys(services: dict[str, Any], entity: str) -> set[str]:
    """Consumer-facing keys the primary entity's ``provides`` declares."""
    raw = services.get(entity)
    if not isinstance(raw, dict):
        return set()
    provides = raw.get("provides")
    values = provides if isinstance(provides, list) else [provides]
    return {item.strip() for item in values if isinstance(item, str) and item.strip()}


def own_eol_block_keys(role_dir: Path) -> set[str]:
    """Keys of the EOL role's own blocks that requirement (a) stores ``false``.

    Args:
        role_dir: the role directory, assumed to carry ``lifecycle: eol``.

    Returns:
        The primary entity key plus every ``canonical`` alias key declared in
        the same file. A ``provides`` value is deliberately absent: it renames
        the key consumers bind, it never names a block in the provider's file.
    """
    services = _load_mapping(role_dir / ROLE_FILE_META_SERVICES)
    entity = get_entity_name(role_dir.name)
    if not entity:
        return set()
    return {entity, *_alias_keys(services, entity)}


def eol_service_keys() -> dict[str, str]:
    """Consumer-facing service key to role id, for every EOL role the rule covers.

    Returns:
        Every key a consumer may bind the role under - the primary entity name,
        each ``provides`` entry and each ``canonical`` alias - mapped to the
        role whose primary entity declares ``lifecycle: eol``. Roles listed by
        :func:`exempt_eol_roles` are left out.
    """
    exempt = set(exempt_eol_roles())
    found: dict[str, str] = {}
    for role_dir in _eol_role_dirs():
        if role_dir.name in exempt:
            continue
        services = _load_mapping(role_dir / ROLE_FILE_META_SERVICES)
        entity = get_entity_name(role_dir.name)
        if not entity:
            continue
        keys = {
            entity,
            *_alias_keys(services, entity),
            *_provided_keys(services, entity),
        }
        for key in keys:
            found[key] = role_dir.name
    return found


def _keys_to_check(role_dir: Path, eol: dict[str, str]) -> dict[str, str]:
    """Service key to provider role, for the keys this role has to answer for.

    Args:
        role_dir: the role being walked.
        eol: the output of :func:`eol_service_keys`.

    Returns:
        For an EOL role, only its own block keys, which requirement (a) binds
        regardless; a foreign key inside an EOL role is omitted, because one
        dead integration may name another. For every other role, every EOL key.
    """
    own = {key for key, provider in eol.items() if provider == role_dir.name}
    if get_role_lifecycle(role_dir) == _EOL:
        return dict.fromkeys(own & own_eol_block_keys(role_dir), role_dir.name)
    return {key: provider for key, provider in eol.items() if key not in own}


def _key_column(raw: str) -> int:
    """Column the mapping key starts in, counting ``- `` sequence markers."""
    stripped = raw.lstrip()
    column = len(raw) - len(stripped)
    while stripped.startswith("- "):
        column += 2
        stripped = stripped[2:]
    return column


def _bare_key_line(raw: str) -> str:
    """The line's content with indentation and ``- `` sequence markers removed."""
    stripped = raw.strip()
    while stripped.startswith("- "):
        stripped = stripped[2:]
    return stripped


def _top_level_key_line(lines: Sequence[str], key: str) -> int:
    """1-based line declaring top-level *key*, or 1 when the key is absent."""
    return next(
        (idx for idx, raw in enumerate(lines, start=1) if raw.startswith(f"{key}:")),
        1,
    )


def _block_field_line(lines: Sequence[str], key: str, field: str) -> int:
    """1-based line of ``field`` one nesting level inside the top-level ``key``.

    Args:
        lines: the ``meta/services.yml`` lines.
        key: the top-level service key.
        field: the field to locate directly inside that block.

    Returns:
        The field's line when it sits at exactly the block's child indent, else
        the key's own line. Matching at any depth would hand the slot to the
        ``enabled: true`` inside a ``modes:`` sub-block, and a ``# nocheck``
        marker on that harmless line would then silence the top-level flag.
    """
    start = next(
        (idx for idx, raw in enumerate(lines) if raw.startswith(f"{key}:")), -1
    )
    if start < 0:
        return 1
    key_indent = len(lines[start]) - len(lines[start].lstrip())
    child_indent = -1
    for idx in range(start + 1, len(lines)):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= key_indent:
            break
        if stripped.startswith("#"):
            continue
        if child_indent < 0:
            child_indent = indent
        if indent == child_indent and stripped.startswith(f"{field}:"):
            return idx + 1
    return start + 1


def _variant_spans(lines: Sequence[str]) -> list[tuple[int, int]]:
    """0-based ``[start, end)`` line span of every variant in a variants.yml.

    A list entry opens with ``-`` followed by whitespace OR by nothing at all:
    a dash alone on its own line is a valid entry start, and missing it shifts
    every later span onto the wrong variant, so an offence anchors inside a
    neighbour and a marker placed there silences the real pin.
    """
    starts = [idx for idx, raw in enumerate(lines) if _LIST_ENTRY_RE.match(raw)]
    return [
        (start, starts[pos + 1] if pos + 1 < len(starts) else len(lines))
        for pos, start in enumerate(starts)
    ]


def _variant_section_span(
    lines: Sequence[str], span: tuple[int, int], section: str
) -> tuple[int, int]:
    """0-based ``[start, end)`` span of one variant's ``services:``/``addons:``.

    Args:
        lines: the ``meta/variants.yml`` lines.
        span: the variant's 0-based ``[start, end)`` line span.
        section: the top-of-variant key whose block to bound.

    Returns:
        The section's own span, or the whole variant span when the section is
        absent - which is what a YAML alias (``addons: *addons_static_off``)
        leaves behind, since the pinned ids live at the anchor instead.
    """
    start, end = span
    for idx in range(start, end):
        stripped = _bare_key_line(lines[idx])
        if stripped != f"{section}:" and not stripped.startswith(f"{section}: "):
            continue
        column = _key_column(lines[idx])
        for inner in range(idx + 1, end):
            if not lines[inner].strip():
                continue
            if _key_column(lines[inner]) <= column:
                return (idx, inner)
        return (idx, end)
    return span


def _variant_field_line(
    lines: Sequence[str], span: tuple[int, int], key: str, field: str
) -> int:
    """1-based line of ``field`` under ``key`` inside one variant's span.

    Args:
        lines: the ``meta/variants.yml`` lines.
        span: the 0-based ``[start, end)`` span to search.
        key: the service or addon key pinned inside it.
        field: the field to locate under that key.

    Returns:
        The field's line, the key's own line when the field is absent, or the
        span's first line when the key is absent - which is also what a
        flow-mapping pin (``jira: {enabled: true}``) and an aliased block
        resolve to, because neither spells the key on a line of its own.
    """
    start, end = span
    for idx in range(start, end):
        bare = _bare_key_line(lines[idx])
        if bare != f"{key}:" and not bare.startswith(f"{key}: "):
            continue
        indent = len(lines[idx]) - len(lines[idx].lstrip())
        for inner in range(idx + 1, end):
            stripped = lines[inner].strip()
            if not stripped:
                continue
            if len(lines[inner]) - len(lines[inner].lstrip()) <= indent:
                break
            if stripped.startswith(f"{field}:"):
                return inner + 1
        return idx + 1
    return start + 1


def _variant_section(variant: Any, section: str) -> dict[str, Any]:
    block = variant.get(section) if isinstance(variant, dict) else None
    return block if isinstance(block, dict) else {}


def _variant_block(variant: Any, section: str, key: str) -> dict[str, Any]:
    entry = _variant_section(variant, section).get(key)
    return entry if isinstance(entry, dict) else {}


def _nested_strings(value: Any) -> list[str]:
    """Every non-blank string *value* holds, at any depth, keys included.

    Strings come back stripped, because the addon runtime resolves a bridge name
    stripped: an unstripped ``"jira "`` would bind nothing here while binding the
    EOL partner at deploy time.
    """
    if isinstance(value, str):
        return [stripped] if (stripped := value.strip()) else []
    if isinstance(value, dict):
        return [
            found
            for key, entry in value.items()
            for item in (key, entry)
            for found in _nested_strings(item)
        ]
    if isinstance(value, (list, tuple, set)):
        return [found for item in value for found in _nested_strings(item)]
    return []


def _addon_bridges(role_dir: Path, addon_id: str) -> list[str]:
    """Service keys the addon's ``bridges:`` key binds.

    Args:
        role_dir: the role owning the addon.
        addon_id: the addon id, i.e. the ``meta/addons/<id>.yml`` stem.

    Returns:
        ``[]`` when the addon declares no ``bridges`` at all, otherwise every
        string the value holds at any depth - which for the canonical list of
        strings is that list. ``test_addons_schema`` is what holds the value to
        the canonical shape, but it is suppressible from the addon's head, so
        reading only that shape would let a scalar ``bridges: jira`` plus one
        ``# nocheck: addon-schema`` bypass this rule entirely while the loader
        still resolves the addon.
    """
    spec = _load_yaml(role_dir / ROLE_DIR_META_ADDONS / f"{addon_id}.yml")
    if not isinstance(spec, dict) or "bridges" not in spec:
        return []
    return _nested_strings(spec["bridges"])


def _addon_gate_re(role: str, key: str) -> re.Pattern[str]:
    """Anchored pattern for the one gate the stored literal contains.

    Args:
        role: the role whose ``meta/services.yml`` stores the flag.
        key: the EOL service key.

    Returns:
        A pattern matching the whole ``enabled`` expression, so a negated or
        ``or``-ed variation of the same lookup cannot pass as containment.
        Either quote character and whitespace after ``lookup(`` and around the
        commas are accepted: they are the same expression, and rejecting them
        buys no containment.
    """
    return re.compile(
        r"^\{\{\s*lookup\(\s*(['\"])config\1\s*,\s*(['\"])"
        + re.escape(role)
        + r"\2\s*,\s*(['\"])services\."
        + re.escape(key)
        + r"\.enabled\3\s*\)\s*\|\s*bool\s*\}\}$"
    )


def _addon_enabled(spec: dict[str, Any]) -> Any:
    """The addon's resolved enable state, as the loader resolves it.

    Args:
        spec: the addon spec mapping.

    Returns:
        The declared ``enabled`` value verbatim, or - when the key is absent -
        the boolean ``required`` falls back to, mirroring
        ``utils.cache.applications._normalize_addons``.
    """
    if _FLAG in spec:
        return spec[_FLAG]
    return bool(spec.get("required", False))


def _exemption_footer() -> str:
    dropped = exempt_eol_roles()
    if not dropped:
        return ""
    return (
        f"\nDropped from the EOL set by '# nocheck: {_PROVIDER_RULE}' in the "
        f"head of their own meta/services.yml, so every consumer of them is "
        f"exempt: {', '.join(dropped)}."
    )


class TestEolDependencyRequiresEolConsumer(unittest.TestCase):
    def test_no_eol_role_exempts_every_consumer(self) -> None:
        self.assertEqual(
            sorted(set(exempt_eol_roles()) - WHOLE_RULE_EXEMPTIONS),
            [],
            f"A '# nocheck: {_PROVIDER_RULE}' in the head of an EOL role's own "
            "meta/services.yml drops every consumer of that service across the "
            "whole repository, so it is not a per-case opt-out and may not land "
            "unreviewed. Keep the marker only for an EOL entity that still "
            "backs a live surface, and record the role in "
            "WHOLE_RULE_EXEMPTIONS in this file together with the reason:\n  "
            + "\n  ".join(sorted(set(exempt_eol_roles()) - WHOLE_RULE_EXEMPTIONS)),
        )

    def test_no_whole_rule_marker_is_bare(self) -> None:
        self.assertEqual(
            sorted(bare_exemption_roles()),
            [],
            f"A '# nocheck: {_PROVIDER_RULE}' exempts every consumer of the "
            "service at once, so it is held to the same bar as a per-flag "
            "marker: it MUST name why the entity still backs a live surface "
            "the rule has no claim on. A bare one grants no exemption and is "
            "reported here rather than left in the tree looking granted:\n  "
            + "\n  ".join(sorted(bare_exemption_roles())),
        )

    def test_no_role_enables_an_eol_service(self) -> None:
        eol = eol_service_keys()
        offenders: list[str] = []

        for role_dir in _role_dirs():
            services_path = role_dir / ROLE_FILE_META_SERVICES
            services = _load_yaml(services_path)
            if not isinstance(services, dict):
                continue
            lines = _lines(services_path)
            rel = services_path.relative_to(PROJECT_ROOT)

            for key, provider in sorted(_keys_to_check(role_dir, eol).items()):
                entry = services.get(key)
                if not isinstance(entry, dict):
                    continue
                line_no = _block_field_line(lines, key, _FLAG)
                suffix = _offence_suffix(lines, line_no)
                if suffix is None:
                    continue

                if provider == role_dir.name and _FLAG not in entry:
                    offenders.append(
                        f"{role_dir.name}: {rel}:{line_no} stores no "
                        f"services.{key}.{_FLAG}, but {provider} is "
                        f"lifecycle: eol and has to carry the literal "
                        f"false{suffix}"
                    )
                elif _FLAG in entry and entry[_FLAG] is not False:
                    offenders.append(
                        f"{role_dir.name}: {rel}:{line_no} declares "
                        f"services.{key}.{_FLAG} = {entry[_FLAG]!r}, but "
                        f"{provider} is lifecycle: eol{suffix}"
                    )

        self.assertEqual(
            offenders,
            [],
            "An EOL service MUST be stored off and may only be enabled by a "
            "role that is itself EOL; every other consumer binds a partner no "
            "CI round deploys. Store `enabled: false` as a literal (a `{{ "
            "'<role>' in group_names }}` gate turns true the moment the EOL "
            f"role joins an inventory), or suppress with '# nocheck: {_RULE}' "
            "naming why the dependency outlives the upstream:\n  "
            + "\n  ".join(offenders)
            + _exemption_footer(),
        )

    def test_no_variant_pins_an_eol_service_on(self) -> None:
        eol = eol_service_keys()
        offenders: list[str] = []

        for role_dir in _role_dirs():
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list) or not variants:
                continue
            lines = _lines(variants_path)
            spans = _variant_spans(lines)
            rel = variants_path.relative_to(PROJECT_ROOT)
            checks = _keys_to_check(role_dir, eol)

            for index, variant in enumerate(variants):
                span = spans[index] if index < len(spans) else (0, len(lines))
                offenders.extend(
                    self._variant_service_offenders(
                        role_dir, variant, checks, lines, span, rel, index
                    )
                )
                offenders.extend(
                    self._variant_addon_offenders(
                        role_dir, variant, checks, lines, span, rel, index
                    )
                )

        self.assertEqual(
            offenders,
            [],
            "No variant may re-enable an EOL service, not even a variant of "
            "the EOL role itself, and not through an addon whose `bridges:` "
            "list names it; that round would deploy an app the lifecycle "
            "envelope excludes from every test. Remove the override so the "
            "literal `false` from meta/services.yml stands (restating it there "
            "is what `variants-static-override` flags), or suppress with "
            f"'# nocheck: {_RULE}' naming why the pin is sound:\n  "
            + "\n  ".join(offenders)
            + _exemption_footer(),
        )

    def _variant_service_offenders(
        self,
        role_dir: Path,
        variant: Any,
        checks: dict[str, str],
        lines: Sequence[str],
        span: tuple[int, int],
        rel: Any,
        index: int,
    ) -> list[str]:
        section = _variant_section_span(lines, span, "services")
        bounds = (span[0] + 1, span[1])
        offenders: list[str] = []
        for key, provider in sorted(checks.items()):
            block = _variant_block(variant, "services", key)
            if _FLAG not in block or block[_FLAG] is False:
                continue
            line_no = _variant_field_line(lines, section, key, _FLAG)
            suffix = _offence_suffix(lines, line_no, bounds)
            if suffix is None:
                continue
            offenders.append(
                f"{role_dir.name}: {rel}:{line_no} variant {index} pins "
                f"services.{key}.{_FLAG} = {block[_FLAG]!r}, but {provider} "
                f"is lifecycle: eol{suffix}"
            )
        return offenders

    def _variant_addon_offenders(
        self,
        role_dir: Path,
        variant: Any,
        checks: dict[str, str],
        lines: Sequence[str],
        span: tuple[int, int],
        rel: Any,
        index: int,
    ) -> list[str]:
        section = _variant_section_span(lines, span, "addons")
        bounds = (span[0] + 1, span[1])
        offenders: list[str] = []
        for addon_id in sorted(_variant_section(variant, "addons")):
            pin = _variant_block(variant, "addons", addon_id)
            if _FLAG not in pin or pin[_FLAG] is False:
                continue
            bound = sorted(
                key for key in _addon_bridges(role_dir, addon_id) if key in checks
            )
            if not bound:
                continue
            line_no = _variant_field_line(lines, section, addon_id, _FLAG)
            suffix = _offence_suffix(lines, line_no, bounds)
            if suffix is None:
                continue
            offenders.extend(
                f"{role_dir.name}: {rel}:{line_no} variant {index} pins "
                f"addons.{addon_id}.{_FLAG} = {pin[_FLAG]!r}, which bridges "
                f"'{key}', but {checks[key]} is lifecycle: eol{suffix}"
                for key in bound
            )
        return offenders

    def test_no_addon_bridges_an_eol_service(self) -> None:
        eol = eol_service_keys()
        offenders: list[str] = []

        for role_dir in _role_dirs():
            if get_role_lifecycle(role_dir) == _EOL:
                continue
            addons_dir = role_dir / ROLE_DIR_META_ADDONS
            if not addons_dir.is_dir():
                continue

            for addon_path in sorted(addons_dir.glob("*.yml")):
                spec = _load_yaml(addon_path)
                if not isinstance(spec, dict):
                    continue
                bound = sorted(
                    {
                        item
                        for item in _addon_bridges(role_dir, addon_path.stem)
                        if item in eol
                    }
                )
                if not bound:
                    continue
                enabled = _addon_enabled(spec)
                if enabled is False:
                    continue
                lines = _lines(addon_path)
                rel = addon_path.relative_to(PROJECT_ROOT)
                line_no = _top_level_key_line(
                    lines, _FLAG if _FLAG in spec else "bridges"
                )

                for key in bound:
                    if isinstance(enabled, str) and _addon_gate_re(
                        role_dir.name, key
                    ).fullmatch(enabled.strip()):
                        continue
                    suffix = _offence_suffix(lines, line_no)
                    if suffix is None:
                        continue
                    offenders.append(
                        f"{role_dir.name}: {rel}:{line_no} bridges '{key}' with "
                        f"{_FLAG} = {enabled!r}, but {eol[key]} is "
                        f"lifecycle: eol{suffix}"
                    )

        self.assertEqual(
            offenders,
            [],
            "An addon of a role that is not itself EOL may bridge an EOL "
            "service only when its own gate cannot turn true: either a literal "
            "`enabled: false`, or exactly `{{ lookup('config', '<own-role>', "
            "'services.<eol-key>.enabled') | bool }}`, which the services walk "
            "holds to a literal false. A gate that merely mentions that lookup "
            "may still render true, and anything else installs an integration "
            "against an app no CI round deploys. Fix the gate or suppress with "
            f"'# nocheck: {_RULE}' naming why the bridge outlives the "
            "upstream:\n  " + "\n  ".join(offenders) + _exemption_footer(),
        )


if __name__ == "__main__":
    unittest.main()
