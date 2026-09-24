"""Extract and machine-translate the gettext catalogs under ``locale/``.

Usage:
  python -m cli.build.i18n extract [--domain core|docs]
  python -m cli.build.i18n translate --domain core|docs [--languages de,fr]
  python -m cli.build.i18n languages [--domain core|docs]
  python -m cli.build.i18n prune [--domain core|docs] [--languages de,fr]
  python -m cli.build.i18n tune [--language de]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import (
    adopt_template,
    build_template,
    catalog_path,
    merge_adopted,
    read_catalog,
    write_catalog,
)
from utils.i18n.client import BATCH_SIZE
from utils.i18n.extract import core_messages, docs_template
from utils.i18n.languages import (
    DOMAINS,
    domain_languages,
    load_languages,
    translatable,
)
from utils.i18n.libretranslate import (
    READY_TIMEOUT_SECONDS,
    LibreTranslate,
    server,
)
from utils.i18n.translate import apply, damaged, discard, pending

CHUNK_SIZE = 500
SPHINX_JOBS_FLOOR = 2


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


def extract(domains: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    for domain in domains:
        if domain == "core":
            template = build_template(core_messages(PROJECT_ROOT), domain)
        else:
            template = docs_template(PROJECT_ROOT, sphinx_jobs())
        codes = list(domain_languages(loaded, domain))
        with tempfile.TemporaryDirectory(prefix="infinito-i18n-pot-") as scratch:
            pot = Path(scratch) / f"{domain}.pot"
            write_catalog(pot, template)
            with ProcessPoolExecutor(
                max_workers=min(len(codes), os.cpu_count() or 1),
                initializer=adopt_template,
                initargs=(str(pot), domain),
            ) as pool:
                changed = sum(
                    pool.map(merge_adopted, [(PROJECT_ROOT, code) for code in codes])
                )
        print(f"{domain}: {len(template)} messages, {changed} catalogs changed")
    return 0


def languages(domains: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    codes = sorted({code for d in domains for code in translatable(loaded, d)})
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
            broken = damaged(catalog)
            if not broken:
                continue
            discard(broken)
            write_catalog(path, catalog)
            cleared += len(broken)
            print(f"{domain}/{code}: {len(broken)} damaged translations cleared")
        print(f"{domain}: {cleared} translations cleared")
    return 0


def usable_cpus() -> int:
    """Return the CPUs this process may run on."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def one_catalog(client: LibreTranslate, domain: str, code: str) -> None:
    """Translate every pending entry of one catalog and write it back.

    Args:
        client: translation client.
        domain: catalog domain.
        code: ISO 639-1 code of the catalog.
    """
    path = catalog_path(PROJECT_ROOT, code, domain)
    catalog = read_catalog(path)
    todo = pending(catalog)
    discarded = refused = damaged = 0
    refusal = ""
    for start in range(0, len(todo), CHUNK_SIZE):
        chunk = todo[start : start + CHUNK_SIZE]
        outcome = client.translate([m.id for m in chunk], code)
        discarded += apply(chunk, outcome.values)
        refused += outcome.refused
        damaged += outcome.damaged
        refusal = outcome.refusal or refusal
        write_catalog(path, catalog)
        print(f"{domain}/{code}: {start + len(chunk)}/{len(todo)}", flush=True)
    tail = f", last refusal {refusal}" if refused else ""
    print(
        f"{domain}/{code}: {len(todo) - discarded} translated, {discarded} discarded "
        f"({refused} requests refused, {damaged} damaged a protected span){tail}",
        flush=True,
    )


def translate(domains: list[str], requested: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    work: list[tuple[str, str]] = []
    for domain in domains:
        supported = translatable(loaded, domain)
        unsupported = sorted(set(requested) - set(supported))
        if unsupported:
            print(f"LibreTranslate does not support {unsupported}", file=sys.stderr)
            return 2
        work += [
            (domain, code)
            for code in (sorted(requested) if requested else supported)
            if pending(read_catalog(catalog_path(PROJECT_ROOT, code, domain)))
        ]
    if not work:
        print(f"{', '.join(domains)}: nothing to translate")
        return 0

    cpus = usable_cpus()
    codes = sorted({code for _, code in work})
    tuned = int(os.environ.get("INFINITO_I18N_LANES") or 0)
    lanes = min(len(work), tuned or cpus)
    batch = int(os.environ.get("INFINITO_I18N_BATCH_SIZE") or BATCH_SIZE)
    with server(PROJECT_ROOT, codes, cpus) as url:
        client = LibreTranslate(url, max(cpus // lanes, 1), batch_size=batch)
        client.wait(codes, READY_TIMEOUT_SECONDS)
        with ThreadPoolExecutor(lanes) as pool:
            for _ in pool.map(lambda job: one_catalog(client, *job), work):
                pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="Update every catalog.")
    extract_parser.add_argument("--domain", choices=DOMAINS)
    translate_parser = commands.add_parser(
        "translate", help="Machine-translate empty and fuzzy entries."
    )
    translate_parser.add_argument("--domain", choices=DOMAINS)
    translate_parser.add_argument(
        "--languages",
        default="",
        help="Comma-separated ISO 639-1 codes; empty for every supported language.",
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
        return extract([args.domain] if args.domain else list(DOMAINS))
    if args.command == "languages":
        return languages([args.domain] if args.domain else list(DOMAINS))
    if args.command == "prune":
        return prune(
            [args.domain] if args.domain else list(DOMAINS),
            [c for c in args.languages.split(",") if c],
        )
    return translate(
        [args.domain] if args.domain else list(DOMAINS),
        [c for c in args.languages.split(",") if c],
    )


if __name__ == "__main__":
    sys.exit(main())
