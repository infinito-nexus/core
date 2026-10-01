"""A translation carried back to English must still resemble its source.

Echo and collapse are visible in the catalog alone. A fluent translation that
means something else is not: it is a well-formed sentence of the right
language and the right length, and only reading it against its source shows
the drift. Carrying it back through the same engine approximates that reading
without a human.

Back-translation is lossy on its own, so the floor is deliberately low. The
check is aimed at a translation sharing almost no content with its source,
not at nuance a round trip would lose anyway.

A sample whose back-translation comes back byte-identical to what was sent is
dropped rather than scored. LibreTranslate answers 200 with the request body
when it has no model for a pair, and the only filter this check can apply
beforehand is ``targets()``, which proves the engine renders *into* a
language, not that it reads *out of* it. Scoring that echo compares an English
source against the untranslated target text, which shares no word with it and
reports 0.00 for a translation nothing is wrong with.
"""

from __future__ import annotations

import re
import unittest

from tests.utils.services import answers as serves
from tests.utils.services import progress as _progress
from utils.i18n.catalog import MACHINE_TRANSLATION, catalog_path, read_catalog
from utils.i18n.languages import load_languages, translatable
from utils.i18n.libretranslate import PIVOT_LANGUAGE, SERVICE_KEY
from utils.i18n.untranslatable import untranslatable
from utils.inventory.tools import LIBRETRANSLATE_ROLE, lane_url

from . import PROJECT_ROOT, SUITE

DOMAIN = "core"
SAMPLES_PER_LANGUAGE = 12
MIN_SOURCE_CHARS = 40
MIN_OVERLAP = 0.3
WORKERS = 4
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def overlap(left: str, right: str) -> float:
    """Return the share of the source's words the back-translation kept.

    Args:
        left: the English source.
        right: the back-translation.

    Returns:
        ``0.0`` to ``1.0``; ``1.0`` when the source carries no word.
    """
    source = {w.lower() for w in WORD.findall(left)}
    carried = {w.lower() for w in WORD.findall(right)}
    if not source:
        return 1.0
    return len(source & carried) / len(source)


class TestBackTranslation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = lane_url(PROJECT_ROOT, LIBRETRANSLATE_ROLE, SERVICE_KEY)
        if not serves(f"{cls.url}/languages"):
            raise unittest.SkipTest(
                f"nothing answers on {cls.url}; `make test-oracle` brings the "
                "tools lane up before the suite runs, and this check cannot "
                "deploy it from inside the stack's container"
            )
        _progress(SUITE, f"LibreTranslate answers on {cls.url}")

    def test_back_translation_keeps_the_source_content(self):
        from utils.i18n.client import LibreTranslate

        client = LibreTranslate(self.url, WORKERS)
        available = client.targets()
        languages = load_languages(PROJECT_ROOT)
        offenders: list[str] = []
        echoed = 0

        for code in translatable(languages, DOMAIN):
            if client.server_code(code) not in available:
                continue
            path = catalog_path(PROJECT_ROOT, code, DOMAIN)
            if not path.is_file():
                continue
            pairs = [
                (str(m.id), str(m.string))
                for m in read_catalog(path)
                if m.id
                and m.string
                and MACHINE_TRANSLATION in (m.user_comments or [])
                and len(str(m.id)) >= MIN_SOURCE_CHARS
                and not untranslatable(str(m.id))
            ]
            if not pairs:
                continue
            stride = max(1, len(pairs) // SAMPLES_PER_LANGUAGE)
            sample = pairs[::stride][:SAMPLES_PER_LANGUAGE]
            _progress(SUITE, f"back-translating {len(sample)} samples of {code}")
            outcome = client.translate([t for _s, t in sample], PIVOT_LANGUAGE)
            for (source, translation), back in zip(
                sample, outcome.values, strict=False
            ):
                if not isinstance(back, str) or not back:
                    continue
                if back == translation:
                    echoed += 1
                    continue
                score = overlap(source, back)
                if score < MIN_OVERLAP:
                    offenders.append(
                        f"{code}: {score:.2f} {source[:50]!r} -> {back[:50]!r}"
                    )

        if echoed:
            _progress(SUITE, f"{echoed} sample(s) the engine could not carry back")

        if offenders:
            self.fail(
                f"{len(offenders)} translation(s) carry back under "
                f"{MIN_OVERLAP:.0%} of their source's words:\n"
                + "\n".join(f"  - {o}" for o in offenders[:40])
                + ("\n  ..." if len(offenders) > 40 else "")
            )
