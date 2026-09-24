"""Fill the Argos download cache in parallel before install_models.py runs."""

from __future__ import annotations

import argparse
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import libretranslate.language
from argostranslate import package

LANES = 8


def wanted(codes: list[str]) -> list:
    """Return the available packages install_models.py would install.

    Args:
        codes: ISO 639-1 codes, empty for every package.
    """
    package.update_package_index()
    available = package.get_available_packages()
    if not codes:
        return available
    keep = set(libretranslate.language.iso2model(codes))
    return [p for p in available if p.from_code in keep and p.to_code in keep]


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
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    available = wanted([c for c in args.load_only_lang_codes.split(",") if c])
    print(f"Prefetching {len(available)} models over {LANES} lanes", flush=True)
    with ThreadPoolExecutor(LANES) as pool:
        for path in pool.map(fetch, available):
            print(f"cached {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
