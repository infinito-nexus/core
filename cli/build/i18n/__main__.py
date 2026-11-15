"""Extract and machine-translate the gettext catalogs under ``locale/``.

Usage:
  python -m cli.build.i18n extract [--domain core|docs]
  python -m cli.build.i18n extract --root <dir> --domain <name>
  python -m cli.build.i18n translate --domain core|docs [--languages de,fr]
  python -m cli.build.i18n translate --root <dir> --domain <name> [--languages de,fr]
  python -m cli.build.i18n languages
  python -m cli.build.i18n prune [--domain core|docs] [--languages de,fr]
  python -m cli.build.i18n retry [--domain core|docs] [--languages de,fr]
  python -m cli.build.i18n tune [--language de]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import (
    adopt_template,
    build_template,
    catalog_path,
    exclusive,
    merge_adopted,
    read_catalog,
    write_catalog,
)
from utils.i18n.client import BATCH_SIZE
from utils.i18n.extract import core_messages, docs_template, keyed_messages
from utils.i18n.gateway import (
    READY_TIMEOUT_SECONDS,
    LibreTranslate,
    download_status,
    server,
)
from utils.i18n.languages import (
    DOMAINS,
    catalog_languages,
    domain_languages,
    load_languages,
)
from utils.i18n.libretranslate import served_languages
from utils.i18n.placeholders import Rejected
from utils.i18n.translate import (
    apply,
    by_exclusion,
    damaged,
    discard,
    over_shared,
    pending,
    retry,
    taken_translations,
)

CHUNK_SIZE = 100
SPHINX_JOBS_FLOOR = 2
CHAT_LANES = 2
DOMAIN_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def sphinx_jobs() -> int:
    """Return the parallel Sphinx processes the cores left over can carry.

    Returns:
        Job count, never below ``SPHINX_JOBS_FLOOR``.
    """
    try:
        usable = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        usable = os.cpu_count() or 1
    return max(SPHINX_JOBS_FLOOR, min(usable, round(usable - os.getloadavg()[0])))


def extract(domains: list[str], root: Path | None) -> int:
    """Merge the current source strings into every catalog of ``domains``.

    Args:
        domains: gettext domains to extract.
        root: directory holding the ``locale/`` of a role or repository
            outside core; ``None`` for core's own ``core`` and ``docs``.
    """
    loaded = load_languages(PROJECT_ROOT)
    target = PROJECT_ROOT if root is None else root
    for domain in domains:
        if root is not None:
            template = build_template(keyed_messages(root, domain), domain)
        elif domain == "core":
            template = build_template(core_messages(PROJECT_ROOT), domain)
        else:
            template = docs_template(PROJECT_ROOT, sphinx_jobs())
        codes = catalog_languages(loaded)
        with tempfile.TemporaryDirectory(prefix="infinito-i18n-pot-") as scratch:
            pot = Path(scratch) / f"{domain}.pot"
            write_catalog(pot, template)
            with ProcessPoolExecutor(
                max_workers=min(len(codes), os.cpu_count() or 1),
                initializer=adopt_template,
                initargs=(str(pot), domain),
            ) as pool:
                changed = sum(
                    pool.map(merge_adopted, [(target, code) for code in codes])
                )
        print(f"{domain}: {len(template)} messages, {changed} catalogs changed")
    return 0


def languages(domains: list[str]) -> int:
    """Print every language carrying a catalog, as a JSON array.

    The caller is the CI matrix of ``entry-pr-translate.yml``, which opens one
    branch and one pull request per code. Every language the repository names
    is translated, so every one of them belongs in the matrix: the gateway
    offers each backend that serves the pair and falls through to its chat
    backend, which declares no catalogue and therefore answers for the pairs
    the dedicated engines do not cover.
    """
    loaded = load_languages(PROJECT_ROOT)
    codes = sorted({code for d in domains for code in domain_languages(loaded, d)})
    print(json.dumps(codes))
    return 0


def prune(domains: list[str], requested: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    for domain in domains:
        codes = requested or domain_languages(loaded, domain)
        cleared = 0
        for code in sorted(codes):
            path = catalog_path(PROJECT_ROOT, code, domain)
            if not path.is_file():
                continue
            catalog = read_catalog(path)
            shared = over_shared(catalog)
            discard(shared)
            broken = damaged(catalog, code)
            discard(broken)
            if not shared and not broken:
                continue
            write_catalog(path, catalog)
            cleared += len(shared) + len(broken)
            print(
                f"{domain}/{code}: {len(broken)} damaged and {len(shared)} "
                "collapsed translations cleared"
            )
        print(f"{domain}: {cleared} translations cleared")
    return 0


def retry_refused(domains: list[str], requested: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    for domain in domains:
        codes = requested or domain_languages(loaded, domain)
        cleared = 0
        for code in sorted(codes):
            path = catalog_path(PROJECT_ROOT, code, domain)
            if not path.is_file():
                continue
            catalog = read_catalog(path)
            offered = retry(catalog)
            if not offered:
                continue
            write_catalog(path, catalog)
            cleared += offered
            print(f"{domain}/{code}: {offered} refusals dropped")
        print(f"{domain}: {cleared} refusals dropped")
    return 0


def usable_cpus() -> int:
    """Return the CPUs this process may run on."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def one_catalog(client: LibreTranslate, root: Path, domain: str, code: str) -> None:
    """Translate every pending entry of one catalog and write it back.

    An entry the judge failed is asked for without every engine it failed
    with, so the groups below each carry their own ``exclude``.

    Args:
        client: translation client.
        root: directory holding the catalog's ``locale/``.
        domain: catalog domain.
        code: ISO 639-1 code of the catalog.
    """
    path = catalog_path(root, code, domain)
    with exclusive(PROJECT_ROOT, domain, code):
        catalog = read_catalog(path)
        todo = pending(catalog)
        taken = taken_translations(catalog)
        discarded = refused = damaged = done = 0
        criteria: Counter[str] = Counter()
        refusal = ""
        for exclude, group in by_exclusion(todo).items():
            for start in range(0, len(group), CHUNK_SIZE):
                chunk = group[start : start + CHUNK_SIZE]
                outcome = client.translate([m.id for m in chunk], code, exclude=exclude)
                criteria.update(
                    value.reason
                    for value in outcome.values
                    if isinstance(value, Rejected)
                )
                discarded += apply(
                    chunk, outcome.values, taken, criteria, outcome.engines
                )
                refused += outcome.refused
                damaged += outcome.damaged
                refusal = outcome.refusal or refusal
                write_catalog(path, catalog)
                done += len(chunk)
                print(f"{domain}/{code}: {done}/{len(todo)}", flush=True)
    tail = f", last refusal {refusal}" if refused else ""
    broke = ", ".join(f"{count} {name}" for name, count in criteria.most_common())
    print(
        f"{domain}/{code}: {len(todo) - discarded} translated, {discarded} discarded "
        f"({refused} requests refused, {damaged} rejected: {broke or 'none'}){tail}",
        flush=True,
    )


def translate(
    domains: list[str],
    requested: list[str],
    redeploy: bool,
    root: Path | None,
    shared: str = "",
) -> int:
    """Machine-translate the pending entries of ``domains`` through the gateway.

    Args:
        domains: gettext domains to translate.
        requested: ISO 639-1 codes to limit the run to; empty for all.
        redeploy: deploy the gateway bundle even when one already answers.
        root: directory holding the ``locale/`` of a role or repository
            outside core; ``None`` for core's own ``core`` and ``docs``.
        shared: base URL of the shared gateway; empty to use or deploy this
            checkout's own.
    """
    loaded = load_languages(PROJECT_ROOT)
    target = PROJECT_ROOT if root is None else root
    work: list[tuple[str, str]] = []
    for domain in domains:
        supported = catalog_languages(loaded)
        unsupported = sorted(set(requested) - set(supported))
        if unsupported:
            print(
                f"{', '.join(unsupported)} is not a language this repository names",
                file=sys.stderr,
            )
            return 2
        work += [
            (domain, code)
            for code in (sorted(requested) if requested else supported)
            if catalog_path(target, code, domain).is_file()
            and pending(read_catalog(catalog_path(target, code, domain)))
        ]
    if not work:
        print(f"{', '.join(domains)}: nothing to translate")
        return 0

    cpus = usable_cpus()
    codes = sorted({code for _, code in work})
    tuned = int(os.environ.get("INFINITO_I18N_LANES") or 0)
    batch = int(os.environ.get("INFINITO_I18N_BATCH_SIZE") or BATCH_SIZE)
    engine = set(served_languages(PROJECT_ROOT))
    passes = (
        ([job for job in work if job[1] in engine], tuned or cpus),
        ([job for job in work if job[1] not in engine], tuned or CHAT_LANES),
    )
    with server(PROJECT_ROOT, redeploy=redeploy, shared=shared) as url:
        LibreTranslate(url, 1, batch_size=batch).wait(
            codes,
            READY_TIMEOUT_SECONDS,
            status=lambda: download_status(PROJECT_ROOT),
        )
        for group, width in passes:
            if not group:
                continue
            lanes = min(len(group), width)
            client = LibreTranslate(url, max(cpus // lanes, 1), batch_size=batch)
            with ThreadPoolExecutor(lanes) as pool:
                for _ in pool.map(
                    partial(one_catalog, client, target), *zip(*group, strict=True)
                ):
                    pass
    return 0


def scope(
    parser: argparse.ArgumentParser, root: str, domain: str | None
) -> tuple[list[str], Path | None]:
    """Return the domains and the root one extract or translate run covers.

    Args:
        parser: the subcommand parser, which reports a bad combination.
        root: ``--root``; empty for core's own catalogs.
        domain: ``--domain``.
    """
    if not root:
        if domain and domain not in DOMAINS:
            parser.error(
                f"--domain {domain} needs --root; core holds {', '.join(DOMAINS)}"
            )
        return ([domain] if domain else list(DOMAINS)), None
    if not domain or not DOMAIN_NAME.fullmatch(domain):
        parser.error(
            "--root needs --domain <name> of lowercase letters, digits and dashes"
        )
    if not Path(root).is_dir():
        parser.error(f"--root {root} is not a directory")
    return [domain], Path(root).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="Update every catalog.")
    translate_parser = commands.add_parser(
        "translate", help="Machine-translate empty and fuzzy entries."
    )
    for scoped in (extract_parser, translate_parser):
        scoped.add_argument("--domain")
        scoped.add_argument(
            "--root",
            default="",
            help="Directory holding the locale/ of a role or repository outside core.",
        )
    translate_parser.add_argument(
        "--languages",
        default="",
        help="Comma-separated ISO 639-1 codes; empty for every supported language.",
    )
    translate_parser.add_argument(
        "--redeploy",
        action="store_true",
        help="Deploy the gateway bundle even when one already answers.",
    )
    translate_parser.add_argument(
        "--gateway",
        default="",
        help="Base URL of the shared gateway; never deployed from here.",
    )
    languages_parser = commands.add_parser(
        "languages", help="Print the machine-translatable codes as a JSON array."
    )
    languages_parser.add_argument("--domain", choices=DOMAINS)
    prune_parser = commands.add_parser(
        "prune", help="Empty translations that altered a protected span."
    )
    prune_parser.add_argument("--domain", choices=DOMAINS)
    prune_parser.add_argument(
        "--languages",
        default="",
        help="Comma-separated ISO 639-1 codes; empty for every language.",
    )
    retry_parser = commands.add_parser(
        "retry", help="Offer the entries a previous run recorded as refused again."
    )
    retry_parser.add_argument("--domain", choices=DOMAINS)
    retry_parser.add_argument(
        "--languages",
        default="",
        help="Comma-separated ISO 639-1 codes; empty for every language.",
    )
    tune_parser = commands.add_parser(
        "tune", help="Measure the fastest client settings on this host."
    )
    tune_parser.add_argument(
        "--language",
        default="de",
        help="ISO 639-1 code the sweep translates into.",
    )
    args = parser.parse_args()
    if args.command == "tune":
        from cli.build.i18n.tune import main as tune_main

        return tune_main(args.language, usable_cpus())
    if args.command == "extract":
        return extract(*scope(extract_parser, args.root, args.domain))
    if args.command == "languages":
        return languages([args.domain] if args.domain else list(DOMAINS))
    if args.command == "prune":
        return prune(
            [args.domain] if args.domain else list(DOMAINS),
            [c for c in args.languages.split(",") if c],
        )
    if args.command == "retry":
        return retry_refused(
            [args.domain] if args.domain else list(DOMAINS),
            [c for c in args.languages.split(",") if c],
        )
    domains, root = scope(translate_parser, args.root, args.domain)
    return translate(
        domains,
        [c for c in args.languages.split(",") if c],
        args.redeploy,
        root,
        args.gateway,
    )


if __name__ == "__main__":
    sys.exit(main())
