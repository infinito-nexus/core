"""Reading, merging and writing the gettext catalogs under ``locale/``."""

from __future__ import annotations

import datetime as dt
import fcntl
import io
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

from utils.i18n.languages import DOMAINS
from utils.i18n.spans import carries_placeholder
from utils.i18n.untranslatable import untranslatable
from utils.software import (
    SOFTWARE_AUTHOR,
    SOFTWARE_CONTACT,
    SOFTWARE_EMAIL,
    SOFTWARE_LICENSE,
    SOFTWARE_URL,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

LOCALE_DIR = Path("locale")
PROJECT = "infinito-nexus"
ENGINE = "libretranslate"
MACHINE_PREFIX = "translated-by:"
JUDGED_PREFIX = "judge-failed:"
UNNAMED_ENGINE = "unnamed"
REFUSAL_PREFIX = "translation-refused:"
REJECTED_PREFIX = "translation-rejected:"
TRANSLATION_REFUSED = f"{REFUSAL_PREFIX} {ENGINE} damaged-span"
STAMP = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
CONTACT = f"{SOFTWARE_AUTHOR} <{SOFTWARE_EMAIL}>"
HEADER = f"""\
# Translations template for PROJECT.
# Copyright (C) YEAR ORGANIZATION
# This file is distributed under the {SOFTWARE_LICENSE}.
# {CONTACT}, YEAR.
# {SOFTWARE_URL}
#"""
OUTSIDE_HEADER = f"""\
# Translations template for PROJECT.
# Copyright (C) YEAR ORGANIZATION
# This file is distributed under the licence of the repository that holds it.
# {CONTACT}, YEAR.
# {SOFTWARE_URL}
#"""


def machine_translation(engine: str = "") -> str:
    """Return the comment marking a machine translation, naming its engine.

    The gateway routes each request on its own, so a catalog holds the work of
    several engines and a constant mark would attribute all of it to one. An
    entry whose engine the gateway did not report is marked ``unnamed`` rather
    than guessed at.

    Args:
        engine: the engine the gateway reported for this entry.
    """
    return f"{MACHINE_PREFIX} {engine or UNNAMED_ENGINE}"


def is_machine_translation(comment: str) -> bool:
    """Whether ``comment`` is the machine-translation mark, whichever engine.

    Args:
        comment: one ``user_comments`` entry of a message.
    """
    return comment.startswith(MACHINE_PREFIX)


def judge_failure(engine: str) -> str:
    """Return the comment recording that the judge failed an engine's answer.

    Args:
        engine: the engine the failed translation's mark named.
    """
    return f"{JUDGED_PREFIX} {engine or UNNAMED_ENGINE}"


def judged_engines(comments: Iterable[str]) -> tuple[str, ...]:
    """Return the engines the judge failed an entry with, sorted.

    ``unnamed`` is left out: the gateway knows no engine by that name, so
    excluding it would change nothing but the request.

    Args:
        comments: one message's ``user_comments``.
    """
    named = {
        comment.removeprefix(JUDGED_PREFIX).strip()
        for comment in comments
        if comment.startswith(JUDGED_PREFIX)
    }
    return tuple(sorted(named - {UNNAMED_ENGINE}))


@contextmanager
def exclusive(root: Path, domain: str, code: str) -> Iterator[None]:
    """Hold the one lock that admits a writer to a catalog.

    A writer reads the catalog once, keeps it in memory, and writes the whole
    file back. Two writers over the same catalog therefore each hold a private
    view and overwrite each other's entries, which is how distinct sources end
    up sharing one translation with every per-entry predicate passing, and how
    a judge pass's failures vanish under a translation run.

    Args:
        root: repository root.
        domain: catalog domain.
        code: ISO 639-1 code of the catalog.
    """
    lock = root / "build" / "i18n" / f"{domain}-{code}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(f"{domain}/{code}: another run holds it, waiting", flush=True)
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def catalog_path(root: Path, code: str, domain: str) -> Path:
    """Return the path of the ``domain`` catalog of language ``code``.

    Args:
        root: repository root.
        code: ISO 639-1 code.
        domain: gettext domain.
    """
    return root / LOCALE_DIR / code / "LC_MESSAGES" / f"{domain}.po"


def new_catalog(domain: str, code: str | None = None) -> Catalog:
    """Return an empty catalog.

    Args:
        domain: gettext domain.
        code: ISO 639-1 code, ``None`` for a template.
    """
    return Catalog(
        locale=code,
        domain=domain,
        project=PROJECT,
        creation_date=STAMP,
        revision_date=STAMP,
        fuzzy=False,
    )


def build_template(messages: Iterable[tuple[str, str]], domain: str) -> Catalog:
    """Return a template catalog holding the translatable part of ``messages``.

    This is the ``core`` domain's counterpart to the sphinx transform the
    ``docs`` domain carries: ``core`` never passes through sphinx, so a message
    that is nothing but a name would otherwise reach its catalog while the same
    message is withheld from the other domain.

    Args:
        messages: ``(msgctxt, msgid)`` pairs; ``msgctxt`` may be ``None``.
        domain: gettext domain.
    """
    template = new_catalog(domain)
    for context, msgid in messages:
        if not untranslatable(msgid):
            template.add(msgid, context=context)
    return template


def read_catalog(path: Path) -> Catalog:
    """Return the catalog stored at ``path``.

    Args:
        path: ``.po`` or ``.pot`` file named after its domain.
    """
    with path.open("rb") as handle:
        return read_po(handle, domain=path.stem)


def merge(template: Catalog, existing: Catalog | None, code: str) -> Catalog:
    """Return ``existing`` updated to the messages of ``template``.

    A changed source becomes an empty entry, a removed source disappears.

    Babel would instead search every removed message for one resembling the
    changed source and carry its translation over as a fuzzy entry. That search
    is quadratic and costs minutes per catalog, while no consumer here reads a
    fuzzy entry: ``translations``, the API and the docs builder all skip it, and
    ``pending`` hands it back to the translator anyway.

    Args:
        template: catalog of the current sources.
        existing: the language's catalog, ``None`` when it does not exist yet.
        code: ISO 639-1 code of the language.
    """
    catalog = existing if existing is not None else new_catalog(template.domain, code)
    catalog.update(template, no_fuzzy_matching=True)
    catalog.obsolete.clear()
    return catalog


def render(catalog: Catalog) -> bytes:
    """Return the deterministic ``.po`` serialisation of ``catalog``.

    Args:
        catalog: the catalog to serialise.
    """
    catalog.creation_date = STAMP
    catalog.revision_date = STAMP
    catalog.fuzzy = False
    catalog.header_comment = HEADER if catalog.domain in DOMAINS else OUTSIDE_HEADER
    catalog.copyright_holder = SOFTWARE_AUTHOR
    catalog.msgid_bugs_address = SOFTWARE_CONTACT
    catalog.last_translator = CONTACT
    catalog.language_team = CONTACT
    for message in catalog:
        if "python-format" in message.flags and not carries_placeholder(message.id):
            message.flags.discard("python-format")
            message.flags.add("no-python-format")
    buffer = io.BytesIO()
    write_po(buffer, catalog, width=0, sort_output=True, ignore_obsolete=True)
    return buffer.getvalue()


def write_catalog(path: Path, catalog: Catalog) -> bool:
    """Write ``catalog`` to ``path`` unless the file already holds it.

    Args:
        path: target ``.po`` file.
        catalog: the catalog to write.

    Returns:
        ``True`` when the file changed.
    """
    content = render(catalog)
    if path.is_file():
        with path.open("rb") as handle:
            if handle.read() == content:
                return False
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    try:
        staging.write_bytes(content)
        staging.replace(path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return True


def translations(catalog: Catalog) -> dict[tuple[str | None, str], str]:
    """Return every usable translation of ``catalog``.

    Args:
        catalog: a language catalog.

    Returns:
        ``(msgctxt, msgid)`` mapped to ``msgstr``; empty and fuzzy entries are
        left out, so their source text stands in.
    """
    return {
        (message.context, message.id): message.string
        for message in catalog
        if message.id
        and isinstance(message.id, str)
        and message.string
        and not message.fuzzy
    }


_TEMPLATE: Catalog | None = None
_DOMAIN = ""


def adopt_template(pot: str, domain: str) -> None:
    """Read the template once per worker process instead of once per language.

    Args:
        pot: path of the template the pool hands to its workers.
        domain: catalog domain the worker merges into.
    """
    global _TEMPLATE, _DOMAIN  # noqa: PLW0603 - a process pool shares state this way
    _TEMPLATE = read_catalog(Path(pot))
    _DOMAIN = domain


def merge_adopted(root_and_code: tuple[Path, str]) -> int:
    """Merge the adopted template into one language catalog.

    Args:
        root_and_code: repository root and the ISO 639-1 code of the catalog.

    Returns:
        1 when the catalog changed on disk, 0 otherwise.
    """
    root, code = root_and_code
    path = catalog_path(root, code, _DOMAIN)
    existing = read_catalog(path) if path.is_file() else None
    return write_catalog(path, merge(_TEMPLATE, existing, code))
