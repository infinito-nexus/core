"""Mirror the kept ``CHANGELOG.md`` entries into the package changelogs.

Both targets (Debian changelog and the RPM ``%changelog`` section) are
fully regenerated on every run from the kept entries plus an
archived-releases notice that points at the documentation site and lists
the archived versions and dates as plain text. The notice is folded into
the body of the oldest kept entry (not appended after the last entry),
because free text after the final entry is not valid changelog data and
makes the native parsers warn. Because the package files are
regenerated, they cannot drift from the CHANGELOG.md SPOT.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from cli.contributing.changelog.archive.changelog_md import md_body_after_header

if TYPE_CHECKING:
    from pathlib import Path

DOCS_URL = "https://docs.infinito.nexus/"
FOOTER_REFERENCE = f"For older releases, see {DOCS_URL}"
FOOTER_LIST_HEADER = "Earlier releases:"
DEFAULT_MAINTAINER = "Kevin Veen-Birkenbach <kevin@veen.world>"
DEBIAN_SIG_TIME = "00:00:00 +0000"

_DEBIAN_DISTRIBUTION = "unstable"
_DEBIAN_URGENCY = "medium"
_RPM_CHANGELOG_RE = re.compile(r"^%changelog\s*$", re.MULTILINE)


def build_package_footer(archived: list[tuple[str, str]]) -> str:
    """Footer block listing every archived release as plain text and
    pointing at :data:`DOCS_URL` for the full history. No links.
    """
    lines = ["", FOOTER_REFERENCE, "", FOOTER_LIST_HEADER]
    lines.extend(f"  {version} ({date})" for version, date in archived)
    return "\n".join(lines) + "\n"


def format_debian_entry(
    version: str,
    date_iso: str,
    body_md: str,
    maintainer: str,
    footer_md: str = "",
) -> str:
    """Render one CHANGELOG.md entry as a Debian changelog stanza.

    Every non-empty line of the markdown body gets a two-space indent so
    Debian's parser accepts it: each change line MUST start with at least
    two spaces, otherwise dpkg treats it as a badly formatted line, loses
    the entry boundary and reports an empty maintainer. Blank lines stay
    blank.

    *footer_md* (the archived-releases notice) is folded into this
    entry's change body — indented like the rest — rather than appended
    after the trailer, because free text after the final ``--`` line is
    not valid changelog data and makes ``dpkg-parsechangelog`` warn. The
    signature time is a placeholder because CHANGELOG.md only carries
    calendar dates.
    """
    sig_date = date.fromisoformat(date_iso).strftime("%a, %d %b %Y")
    body = md_body_after_header(f"## [{version}] - {date_iso}\n{body_md}")
    lines = body.rstrip().split("\n")
    if footer_md:
        lines.extend(footer_md.rstrip("\n").split("\n"))
    lines = ["  " + ln if ln.strip() else ln for ln in lines]
    body_text = "\n".join(lines)
    return (
        f"infinito-nexus ({version}-1) {_DEBIAN_DISTRIBUTION}; "
        f"urgency={_DEBIAN_URGENCY}\n"
        f"\n"
        f"{body_text}\n"
        f"\n"
        f" -- {maintainer}  {sig_date} {DEBIAN_SIG_TIME}\n"
    )


def format_rpm_entry(
    version: str,
    date_iso: str,
    body_md: str,
    maintainer: str,
    footer_md: str = "",
) -> str:
    """Render one CHANGELOG.md entry as an RPM ``%changelog`` stanza.

    Every non-empty body line gets a ``- `` continuation prefix so rpm
    does not read a markdown ``*`` bullet at column 0 as a new changelog
    entry header (which makes ``rpmspec`` report ``bad date``). Blank
    lines stay blank. *footer_md* (the archived-releases notice) is
    folded into this entry's body for the same reason it is on the Debian
    side: trailing free text confuses the parser.
    """
    rpm_date = date.fromisoformat(date_iso).strftime("%a %b %d %Y")
    body = md_body_after_header(f"## [{version}] - {date_iso}\n{body_md}")
    lines = body.rstrip().split("\n")
    if footer_md:
        lines.extend(footer_md.rstrip("\n").split("\n"))
    lines = ["- " + ln if ln.strip() else ln for ln in lines]
    body_text = "\n".join(lines)
    return f"* {rpm_date} {maintainer} - {version}-1\n{body_text}\n"


def mirror_to_debian_changelog(
    path: Path,
    entries: list[tuple[str, str, str]],
    archived: list[tuple[str, str]],
    *,
    maintainer: str = DEFAULT_MAINTAINER,
    dry_run: bool = False,
) -> bool:
    """Regenerate the Debian changelog at *path* from CHANGELOG.md.

    *entries* is the list of ``(version, date, body_markdown)`` tuples
    for the kept releases. *archived* is the list of
    ``(version, date)`` tuples for older releases that go into the
    trailing notice.

    Returns ``True`` when the file was rewritten, ``False`` when
    nothing happened (no entries or dry run).
    """
    if not entries:
        return False
    footer = build_package_footer(archived) if archived else ""
    last = len(entries) - 1
    blocks = [
        format_debian_entry(v, d, b, maintainer, footer if i == last else "")
        for i, (v, d, b) in enumerate(entries)
    ]
    new_content = "\n".join(blocks).rstrip() + "\n"
    if dry_run:
        return True
    if path.is_file():
        # nocheck below: idempotency check immediately before write; cache would mask non-idempotency
        current = path.read_text(encoding="utf-8")  # nocheck: cache-read
        if current == new_content:
            return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return True


def mirror_to_rpm_spec_changelog(
    path: Path,
    entries: list[tuple[str, str, str]],
    archived: list[tuple[str, str]],
    *,
    maintainer: str = DEFAULT_MAINTAINER,
    dry_run: bool = False,
) -> bool:
    """Regenerate the ``%changelog`` section of an RPM spec file at
    *path* from CHANGELOG.md.

    The file's pre-``%changelog`` head is preserved verbatim. The
    ``%changelog`` section is replaced with one stanza per entry plus
    the trailing notice. Returns ``True`` when the file was rewritten,
    ``False`` when nothing happened (missing file, no ``%changelog``
    section, no entries, or dry run).
    """
    if not entries or not path.is_file():
        return False
    content = path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read — function reads spec file then rewrites it; cached value would go stale on subsequent calls
    section = _RPM_CHANGELOG_RE.search(content)
    if section is None:
        return False
    head = content[: section.end()] + "\n"
    footer = build_package_footer(archived) if archived else ""
    last = len(entries) - 1
    blocks = [
        format_rpm_entry(v, d, b, maintainer, footer if i == last else "")
        for i, (v, d, b) in enumerate(entries)
    ]
    new_changelog = "\n".join(blocks).rstrip() + "\n"
    new_content = head + new_changelog
    if dry_run:
        return True
    if new_content == content:
        return True
    path.write_text(new_content, encoding="utf-8")
    return True
