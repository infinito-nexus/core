"""Install the Argos models this deployment needs, in parallel.

Upstream's scripts/install_models.py keeps both directions of every pair
because it matches a package when from_code AND to_code are both wanted, so a
direction cannot be expressed through --load_only_lang_codes. This replaces it
and therefore also pulls the MiniSBD models its caller would have installed.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import libretranslate.language
from argostranslate import package
from minisbd import download_models

LANES = 8
SOURCE = "en"
DIRECTIONS = ("both", "from_source")


def wanted(codes: list[str], directions: str) -> tuple[list, list[str]]:
    """Return the packages this deployment installs and the codes MiniSBD needs.

    Args:
        codes: ISO 639-1 codes, empty for every package.
        directions: ``both`` keeps every pair, ``from_source`` keeps only the
            ones translating out of the source language.

    Returns:
        The packages to install, and the model codes ``download_models`` takes.

    Raises:
        ValueError: a requested code no package offers, or an empty selection.
    """
    package.update_package_index()
    available = package.get_available_packages()
    model_codes: list[str] = []
    if codes:
        model_codes = libretranslate.language.iso2model(codes)
        keep = set(model_codes)
        offered = {c for p in available for c in (p.from_code, p.to_code)}
        if keep - offered:
            raise ValueError(
                f"Unavailable language codes: {','.join(sorted(keep - offered))}"
            )
        available = [p for p in available if p.from_code in keep and p.to_code in keep]
    if directions == "from_source":
        available = [p for p in available if p.from_code == SOURCE]
    if not available:
        raise ValueError("no available package")
    return available, model_codes


def fetch(available) -> Path:
    """Download one package, dropping a truncated file the cache would keep.

    ``download()`` returns any existing file untouched, so an archive left
    half-written by a killed build is served to every later build as well.
    """
    path = available.download()
    if not zipfile.is_zipfile(path):
        Path(path).unlink()
        raise RuntimeError(f"{path} is not a valid argosmodel archive")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--load_only_lang_codes", type=str, default="")
    parser.add_argument("--directions", choices=DIRECTIONS, default="both")
    args = parser.parse_args()

    codes = [c for c in args.load_only_lang_codes.split(",") if c]
    available, model_codes = wanted(codes, args.directions)
    print(
        f"Installing {len(available)} models ({args.directions}) over {LANES} lanes",
        flush=True,
    )
    with ThreadPoolExecutor(LANES) as pool:
        paths = list(pool.map(fetch, available))
    for path in paths:
        package.install_from_path(path)
    download_models(model_codes or None, print)
    print(f"Installed {len(paths)} models", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
