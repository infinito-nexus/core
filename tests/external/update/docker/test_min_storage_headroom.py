"""Cap how far a service's ``min_storage`` may exceed its image's real size.

``min_storage`` is what the storage guard and the runner packer budget a deploy
against, so an over-declared value makes a host look too small and triggers a
cache-destroying prune on a deploy that would have fit. Every declaration that
also names a concrete ``image:`` and ``version:`` therefore stays within 1 GB of
what a pull of that tag actually transfers, or carries an explicit justification
for the higher number.

The measured size is the manifest's config blob plus every layer blob, resolved
for linux/amd64. It is a lower bound on what the service occupies: the extracted
on-disk footprint exceeds the compressed transfer size, and for a ``custom: true``
service the declared image is only the Dockerfile base, so the deployed image
carries further layers. The gate therefore only ever asks for more justification
than a perfect measurement would, never less.

Opt-in external test: it reads live manifests from third-party registries and
runs only under the external suite. It fails on a positively measured
over-declaration; a registry that answers indeterminately (network error, auth
wall, rate limit) warns instead, so a private or throttled registry never turns
into a false failure.

Convention
==========
On the ``min_storage`` line, or on the contiguous comment lines directly above
it, add both markers on one comment line:

    # nocheck: min-storage-headroom  Reason: <what occupies the space>
    min_storage: 20GB

The ``nocheck`` opts into the exemption; the ``Reason:`` states what the value
budgets for. Both are required, in either order.
"""

from __future__ import annotations

import concurrent.futures
import re
import unittest
from dataclasses import dataclass

from utils.annotations.message import warning
from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.docker.image.discovery import load_yaml
from utils.docker.registry import manifest_transfer_size
from utils.roles.applications.services.resources import _parse_mem_bytes
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import resolve_max_fetch_workers

from . import PROJECT_ROOT

_RULE = "min-storage-headroom"
_HEADROOM_BYTES = 1_000_000_000
_GIB = 1024**3

_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):")
_MIN_STORAGE_KEY = re.compile(r"^\s+min_storage:")
_REASON = re.compile(r"#.*\breason\b\s*:\s*\S", re.IGNORECASE)


@dataclass(frozen=True)
class _Declaration:
    role: str
    service: str
    raw: object
    line: int
    image: str
    version: str


def _min_storage_lines(lines: list[str]) -> dict[str, int]:
    """Map each top-level service key to the 1-based line of its ``min_storage``."""
    found: dict[str, int] = {}
    current: str | None = None
    for line_no, line in enumerate(lines, start=1):
        key = _TOP_LEVEL_KEY.match(line)
        if key:
            current = key.group(1)
            continue
        if current and _MIN_STORAGE_KEY.match(line):
            found.setdefault(current, line_no)
    return found


def _declarations(role_name: str) -> tuple[list[_Declaration], list[str]]:
    path = PROJECT_ROOT / "roles" / role_name / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return [], []
    services = load_yaml(path)
    if not isinstance(services, dict):
        return [], []
    lines = read_text(str(path)).splitlines()
    line_of = _min_storage_lines(lines)
    out = [
        _Declaration(
            role=role_name,
            service=str(service),
            raw=cfg["min_storage"],
            line=line_of.get(str(service), 0),
            image=str(cfg.get("image") or "").strip(),
            version=str(cfg.get("version") or "").strip(),
        )
        for service, cfg in services.items()
        if isinstance(cfg, dict) and "min_storage" in cfg
    ]
    return out, lines


def _justified(lines: list[str], line_no: int) -> bool:
    """Whether the declaration at 1-based *line_no* carries marker and reason.

    Scanned on that line and across the contiguous comment lines directly above
    it; the order of the two markers within that block does not matter.
    """
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False
    has_rule = line_has_rule(lines[idx], _RULE)
    has_reason = bool(_REASON.search(lines[idx]))
    scan = idx - 1
    while scan >= 0 and lines[scan].lstrip().startswith("#"):
        has_rule = has_rule or line_has_rule(lines[scan], _RULE)
        has_reason = has_reason or bool(_REASON.search(lines[scan]))
        scan -= 1
    return has_rule and has_reason


def _measure(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], int | None]:
    def _one(pair: tuple[str, str]) -> tuple[tuple[str, str], int | None]:
        image, version = pair
        return pair, manifest_transfer_size(image, version)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=resolve_max_fetch_workers()
    ) as pool:
        return dict(pool.map(_one, sorted(pairs)))


class TestMinStorageHeadroom(unittest.TestCase):
    def test_min_storage_stays_within_image_size_plus_headroom(self) -> None:
        roles_dir = PROJECT_ROOT / "roles"
        declarations: list[_Declaration] = []
        lines_of_role: dict[str, list[str]] = {}
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
            role_declarations, lines = _declarations(role_dir.name)
            if role_declarations:
                declarations.extend(role_declarations)
                lines_of_role[role_dir.name] = lines
        self.assertTrue(declarations, "No min_storage declarations discovered")

        unlocated = [d for d in declarations if d.line == 0]
        self.assertFalse(
            unlocated,
            "min_storage declared in the parsed YAML but not locatable in the file "
            "text, so no suppression marker could be resolved for it:\n"
            + "\n".join(f"  {d.role}/{d.service}" for d in sorted(unlocated, key=str)),
        )

        candidates = [d for d in declarations if d.image and d.version]
        sizes = _measure({(d.image, d.version) for d in candidates})

        offenders: list[tuple[_Declaration, int, int]] = []
        for d in sorted(candidates, key=lambda c: (c.role, c.service)):
            source = f"roles/{d.role}/{ROLE_FILE_META_SERVICES}"
            need = _parse_mem_bytes(d.raw)
            if need is None:
                warning(
                    f"{d.role}/{d.service}: min_storage {d.raw!r} is not a parsable "
                    "size, so it counts as nothing in every storage budget",
                    title="📏 Unparsable min_storage",
                    file=source,
                )
                continue
            size = sizes.get((d.image, d.version))
            if size is None:
                warning(
                    f"{d.role}/{d.service}: {d.image}:{d.version} manifest size "
                    "could not be read (network / auth / rate-limit)",
                    title="🔍 Unmeasured image size",
                    file=source,
                )
                continue
            justified = _justified(lines_of_role[d.role], d.line)
            if need <= size + _HEADROOM_BYTES:
                if justified:
                    warning(
                        f"{d.role}/{d.service}: min_storage {d.raw} now fits within "
                        f"{size / _GIB:.3f} GiB + 1 GB, so the "
                        f"`{_RULE}` exemption is stale and can go",
                        title="🧹 Stale min_storage exemption",
                        file=source,
                    )
                continue
            if not justified:
                offenders.append((d, need, size))

        if offenders:
            formatted = "\n".join(
                f"  roles/{d.role}/{ROLE_FILE_META_SERVICES}:{d.line}: "
                f"{d.service} declares {d.raw} but {d.image}:{d.version} transfers "
                f"{size / _GIB:.3f} GiB — {(need - size - _HEADROOM_BYTES) / _GIB:.3f} "
                "GiB above image + 1 GB"
                for d, need, size in offenders
            )
            self.fail(
                "These services declare more than 1 GB above the measured size of "
                "their own image. An over-declared min_storage makes a host look "
                "too small and prunes a cache the deploy did not need to lose.\n\n"
                "Fix: lower the value, or state what occupies the space by adding "
                "both markers on one comment line above the key:\n\n"
                f"    # nocheck: {_RULE}  Reason: <what occupies the space>\n"
                "    min_storage: 20GB\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
