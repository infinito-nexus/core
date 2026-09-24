"""Measure the fastest client settings against the deployed LibreTranslate.

The server's own thread count follows the CPUs its container may use, which a
deploy decides; only the client side is free to vary per run. This sweeps it
against real catalog entries and records the winner for the env builder, so a
tuned host keeps its numbers across every `make dotenv`.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.i18n.catalog import catalog_path, read_catalog
from utils.i18n.languages import load_languages, translatable
from utils.i18n.libretranslate import READY_TIMEOUT_SECONDS, LibreTranslate, server
from utils.i18n.translate import pending

TUNING_FILE = Path("build") / "i18n-tuning.json"
SAMPLE_SIZE = 400
BATCH_SIZES = (10, 20, 40, 80)
LANE_FACTORS = (0.5, 1.0, 2.0)


def sample(domain: str, code: str) -> list[str]:
    """Return real source strings the tuner measures against.

    Args:
        domain: catalog domain to draw from.
        code: ISO 639-1 code of the catalog.
    """
    catalog = read_catalog(catalog_path(PROJECT_ROOT, code, domain))
    todo = pending(catalog)
    if len(todo) < SAMPLE_SIZE:
        todo = (todo * (SAMPLE_SIZE // max(len(todo), 1) + 1))[:SAMPLE_SIZE]
    return [message.id for message in todo[:SAMPLE_SIZE]]


def rate(url: str, texts: list[str], code: str, batch: int, lanes: int) -> float:
    """Return entries per second for one setting pair.

    Args:
        url: base URL of the running server.
        texts: the sample every setting pair is measured against.
        code: target language.
        batch: texts per request.
        lanes: concurrent requests.
    """
    client = LibreTranslate(url, 1, batch_size=batch)
    width = max(len(texts) // lanes, 1)
    slices = [texts[i : i + width] for i in range(0, len(texts), width)]
    started = time.monotonic()
    with ThreadPoolExecutor(lanes) as pool:
        for _ in pool.map(lambda chunk: client.translate(chunk, code), slices):
            pass
    return len(texts) / (time.monotonic() - started)


def tune(cpus: int, code: str) -> dict:
    """Sweep the client settings and return the fastest pair.

    Args:
        cpus: the CPU count lane factors scale from.
        code: target language the sweep translates into.
    """
    texts = sample("docs", code)
    results: list[dict] = []
    with server(PROJECT_ROOT, [code], cpus) as url:
        client = LibreTranslate(url, 1)
        client.wait([code], READY_TIMEOUT_SECONDS)
        for batch in BATCH_SIZES:
            for factor in LANE_FACTORS:
                lanes = max(int(cpus * factor), 1)
                measured = rate(url, texts, code, batch, lanes)
                results.append(
                    {
                        "batch_size": batch,
                        "lanes": lanes,
                        "entries_per_second": measured,
                    }
                )
                print(
                    f"batch={batch:3d} lanes={lanes:3d} {measured:7.1f} entries/s",
                    flush=True,
                )
    best = max(results, key=lambda r: r["entries_per_second"])
    return {"best": best, "measurements": results}


def write(outcome: dict) -> Path:
    """Persist the sweep so the env builder can read it.

    Args:
        outcome: what ``tune`` returned.
    """
    path = PROJECT_ROOT / TUNING_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    return path


def main(code: str, cpus: int) -> int:
    """Run the sweep and record its winner.

    Args:
        code: target language the sweep translates into.
        cpus: the CPU count lane factors scale from.

    Returns:
        0 on success, 2 when no catalog offers the language.
    """
    if code not in translatable(load_languages(PROJECT_ROOT), "docs"):
        print(f"LibreTranslate does not support {code}")
        return 2
    outcome = tune(cpus, code)
    best = outcome["best"]
    path = write(outcome)
    print(
        f"best: batch_size={best['batch_size']} lanes={best['lanes']} "
        f"({best['entries_per_second']:.1f} entries/s), written to {path}",
        flush=True,
    )
    print("Run `make dotenv-force` to publish the values into .env.", flush=True)
    return 0
