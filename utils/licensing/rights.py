"""What a licence grants, requires and disclaims, as one boolean per field.

The fields are the taxonomy ``choosealicense.com`` publishes, so each value is
checkable against an outside source instead of this repository's opinion:

* **Grants** -- ``commercial_use``, ``modifications``, ``distribution``,
  ``private_use``, ``patent_use``, ``self_host``. True when the licence allows
  it. ``self_host`` is the question this repository actually asks and the one
  field the upstream taxonomy has no column for.
* **Duties** -- ``include_copyright``, ``document_changes``,
  ``disclose_source``, ``network_use_disclose``, ``same_license``. True when
  the licence demands it.
* **Disclaimers** -- ``liability``, ``warranty``. True when the licence
  disclaims it, which is the normal case and favours the author.
* **Not granted** -- ``trademark_use``. True only where the licence grants
  trademark rights, which almost none do.

``open_source`` is not a right. It records whether the licence meets the Open
Source Definition and is the only thing that separates a source-available
grant (Elastic-2.0, BUSL, SSPL, the n8n Sustainable Use Licence) from a
permissive one: those four allow commercial use and modification, so no column
of the taxonomy tells them apart.

An expression combines ids with ``AND`` and ``OR``. ``AND`` means every licence
applies at once, so the strictest wins: grants intersect, duties and
disclaimers union. ``OR`` means the licensee picks one whole licence, so the
alternative with the most favourable context wins and its own row is used.
Folding ``OR`` field by field would invent a licence nobody offers: Redis under
``AGPL-3.0-only OR RSALv2 OR SSPL-1.0`` would come out carrying no duty at all,
because no single duty is common to all three.
"""

from __future__ import annotations

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.licensing.contexts import (
    COPYLEFT,
    COPYLEFT_NETWORK,
    NON_COMMERCIAL,
    ORDER,
    PERMISSIVE,
    PROPRIETARY,
    SOURCE_AVAILABLE,
    UNKNOWN,
    Context,
)

TABLE = PROJECT_ROOT / "meta" / "licenses.yml"

GRANTS = (
    "commercial_use",
    "modifications",
    "distribution",
    "private_use",
    "patent_use",
    "self_host",
)
DUTIES = (
    "include_copyright",
    "document_changes",
    "disclose_source",
    "network_use_disclose",
    "same_license",
)
DISCLAIMERS = ("liability", "warranty")
NOT_GRANTED = ("trademark_use",)

FIELDS = GRANTS + DUTIES + DISCLAIMERS + NOT_GRANTED

_FLAG = "open_source"


def table() -> dict[str, dict[str, bool]]:
    """Return the licence table keyed by SPDX id."""
    return load_yaml(str(TABLE))


def _all_of(rows: list[dict[str, bool]]) -> dict[str, bool]:
    """Fold licences that apply simultaneously into one row.

    Args:
        rows: the rights of each licence joined by ``AND``.
    """
    folded: dict[str, bool] = {}
    for field in (*FIELDS, _FLAG):
        values = [bool(row.get(field)) for row in rows]
        folded[field] = (
            all(values) if field in GRANTS + NOT_GRANTED + (_FLAG,) else any(values)
        )
    return folded


def resolve(expression: str, inline: dict[str, bool] | None) -> dict[str, bool] | None:
    """Return the rights of an SPDX expression, or None when unknown.

    Args:
        expression: one id, or ids joined by ``AND`` / ``OR``; ``OR`` binds
            loosest, so ``A AND B OR C`` reads as ``(A AND B) OR C``.
        inline: rights the role declares itself, used when the expression
            names a single id the table does not carry.
    """
    known = table()
    alternatives = [part.strip() for part in expression.split(" OR ")]
    resolved: list[dict[str, bool]] = []

    for alternative in alternatives:
        ids = [part.strip() for part in alternative.split(" AND ")]
        rows = [known[one] for one in ids if one in known]
        if len(rows) != len(ids):
            if len(ids) == 1 and inline is not None:
                rows = [inline]
            else:
                return None
        resolved.append(rows[0] if len(rows) == 1 else _all_of(rows))

    return min(resolved, key=lambda row: ORDER.index(context_of(row).key))


def context_of(rights: dict[str, bool] | None) -> Context:
    """Classify rights into the context the generated page groups by.

    Args:
        rights: a resolved rights row, or None when the licence is unread.

    The order is the discriminating one, not the order of the fields.
    ``commercial_use`` is asked first because it is the question a deployer
    brings to the page; a vendor grant that reserves commercial use is
    non-commercial even though it is also closed.
    """
    if rights is None:
        return UNKNOWN
    if not rights.get("commercial_use"):
        return NON_COMMERCIAL
    if not rights.get("modifications"):
        return PROPRIETARY
    if not rights.get(_FLAG):
        return SOURCE_AVAILABLE
    if rights.get("network_use_disclose"):
        return COPYLEFT_NETWORK
    if rights.get("same_license"):
        return COPYLEFT
    return PERMISSIVE
