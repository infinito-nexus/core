"""Extract and machine-translate the gettext catalogs under ``locale/``.

Usage:
  python -m cli.build.i18n extract [--domain core|docs]
  python -m cli.build.i18n translate --domain core|docs [--languages de,fr]
  python -m cli.build.i18n languages [--domain core|docs]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import (
    build_template,
    catalog_path,
    merge,
    read_catalog,
    write_catalog,
)
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
    container,
    pinned_image,
)
from utils.i18n.translate import apply, pending

CHUNK_SIZE = 500


def extract(domains: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    for domain in domains:
        if domain == "core":
            template = build_template(core_messages(PROJECT_ROOT), domain)
        else:
            template = docs_template(PROJECT_ROOT, os.cpu_count())
        changed = 0
        for code in domain_languages(loaded, domain):
            path = catalog_path(PROJECT_ROOT, code, domain)
            existing = read_catalog(path) if path.is_file() else None
            changed += write_catalog(path, merge(template, existing, code))
        print(f"{domain}: {len(template)} messages, {changed} catalogs changed")
    return 0


def languages(domains: list[str]) -> int:
    loaded = load_languages(PROJECT_ROOT)
    codes = sorted({code for d in domains for code in translatable(loaded, d)})
    print(json.dumps(codes))
    return 0


def translate(domain: str, requested: list[str]) -> int:
    supported = translatable(load_languages(PROJECT_ROOT), domain)
    unsupported = sorted(set(requested) - set(supported))
    if unsupported:
        print(f"LibreTranslate does not support {unsupported}", file=sys.stderr)
        return 2
    codes = [
        code
        for code in (sorted(requested) if requested else supported)
        if pending(read_catalog(catalog_path(PROJECT_ROOT, code, domain)))
    ]
    if not codes:
        print(f"{domain}: nothing to translate")
        return 0
    threads = os.cpu_count()
    with container(pinned_image(PROJECT_ROOT), codes, threads) as url:
        client = LibreTranslate(url, threads)
        client.wait(codes, READY_TIMEOUT_SECONDS)
        for code in codes:
            path = catalog_path(PROJECT_ROOT, code, domain)
            catalog = read_catalog(path)
            todo = pending(catalog)
            discarded = 0
            for start in range(0, len(todo), CHUNK_SIZE):
                chunk = todo[start : start + CHUNK_SIZE]
                discarded += apply(chunk, client.translate([m.id for m in chunk], code))
                write_catalog(path, catalog)
                print(
                    f"{domain}/{code}: {start + len(chunk)}/{len(todo)}", flush=True
                )
            print(
                f"{domain}/{code}: {len(todo) - discarded} translated, "
                f"{discarded} discarded",
                flush=True,
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="Update every catalog.")
    extract_parser.add_argument("--domain", choices=DOMAINS)
    translate_parser = commands.add_parser(
        "translate", help="Machine-translate empty and fuzzy entries."
    )
    translate_parser.add_argument("--domain", choices=DOMAINS, required=True)
    translate_parser.add_argument(
        "--languages",
        default="",
        help="Comma-separated ISO 639-1 codes; empty for every supported language.",
    )
    languages_parser = commands.add_parser(
        "languages", help="Print the machine-translatable codes as a JSON array."
    )
    languages_parser.add_argument("--domain", choices=DOMAINS)
    args = parser.parse_args()
    if args.command == "extract":
        return extract([args.domain] if args.domain else list(DOMAINS))
    if args.command == "languages":
        return languages([args.domain] if args.domain else list(DOMAINS))
    return translate(args.domain, [c for c in args.languages.split(",") if c])


if __name__ == "__main__":
    sys.exit(main())
