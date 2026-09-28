"""Ask System One whether a translation still says what its source said.

The other checks in this suite reason about the text mechanically: bytes equal
to the source, one translation shared by many sources. A translation that is
fluent, distinct and simply wrong passes both. Deciding that needs a model
that reads meaning, which is what ``svc-ai-s1`` serves.

The answer is read as an ordering, never as an absolute. ``noul`` is a
probability the server does not centre on 0.5 — its own probe measures 0.5908
for a plainly false text against 0.9507 for a true one — so a fixed threshold
would encode this deployment's calibration. Every run therefore carries two
controls built from the catalog itself: a translation against its own source,
and the same source against a translation belonging to a different entry. A
candidate counts as a mismatch when it scores no better than the deliberately
mismatched control. If the two controls do not separate, the classifier is not
reading its input and the run is inconclusive rather than green.

The server is brought up when it does not answer, so the check runs on a
machine that happens to have nothing deployed. It skips only when the stack is
already held by another deploy, which the lane refuses to race.
"""

from __future__ import annotations

import json
import unittest
import urllib.request

from tests.utils.services import answers as serves
from tests.utils.services import progress as _progress
from utils.cache.yaml import load_yaml
from utils.i18n.catalog import MACHINE_TRANSLATION, catalog_path, read_catalog
from utils.i18n.spans import prose
from utils.inventory.tools import API_KEY, S1_ROLE, lane_url
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT, SUITE

SERVICES_FILE = PROJECT_ROOT / "roles" / S1_ROLE / ROLE_FILE_META_SERVICES
QUESTION = "equivalent"
LANGUAGE = "de"
DOMAIN = "core"
SAMPLES = 8
MIN_SOURCE_CHARS = 40
MIN_SEPARATION = 0.2
TIMEOUT = 120
CRITERIA = {
    "true": "the second text states the same thing as the first text",
    "false": "the second text states something else than the first text",
}


def _base_url() -> str:
    """Return the address this container reaches the lane's System One on."""
    return lane_url(PROJECT_ROOT, S1_ROLE, "s1")


def _model() -> str:
    return load_yaml(SERVICES_FILE)["s1"]["model_alias"]


def ask(base: str, key: str, source: str, translation: str, model: str) -> float:
    """Return the server's ``noul`` for "these two say the same thing".

    Args:
        base: ``http://host:port`` of the server.
        key: bearer key.
        source: the English source.
        translation: the translation to judge.
        model: model alias to address.

    Raises:
        TypeError: the server answered without a numeric ``noul``.
    """
    state = f"First text: {source}\n\nSecond text: {translation}"
    payload = json.dumps(
        {
            "state": state,
            "model": model,
            "questions": {
                QUESTION: {
                    "type": "noul",
                    "instructions": (
                        "Decide whether the second text is a faithful "
                        "translation of the first text."
                    ),
                    "criteria": CRITERIA,
                }
            },
        }
    )
    request = urllib.request.Request(  # noqa: S310 - this repository's own service definition
        base + "/v1/systemone",
        data=payload.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(  # noqa: S310 - this repository's own service definition
        request, timeout=TIMEOUT
    ) as response:
        answers = json.loads(response.read().decode() or "{}").get("answers") or {}
    value = (answers.get(QUESTION) or {}).get("noul")
    if not isinstance(value, (int, float)):
        raise TypeError(f"System One answered noul={value!r}, which is not a number")
    return float(value)


def _pairs() -> list[tuple[str, str]]:
    """Return machine-translated (source, translation) pairs worth judging."""
    path = catalog_path(PROJECT_ROOT, LANGUAGE, DOMAIN)
    if not path.is_file():
        return []
    return [
        (str(m.id), str(m.string))
        for m in read_catalog(path)
        if m.id
        and m.string
        and MACHINE_TRANSLATION in (m.user_comments or [])
        and len(prose(str(m.id)).strip()) >= MIN_SOURCE_CHARS
    ]


class TestSystemOneEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = _pairs()
        if len(cls.pairs) < 2:
            raise unittest.SkipTest(f"{DOMAIN}/{LANGUAGE} carries too few translations")
        cls.base = _base_url()
        cls.model = _model()
        cls.key = API_KEY
        if not serves(f"{cls.base}/health"):
            raise unittest.SkipTest(
                f"nothing answers on {cls.base}; `make test-oracle` brings the "
                "tools lane up before the suite runs, and this check cannot "
                "deploy it from inside the stack's container"
            )
        _progress(SUITE, f"System One answers on {cls.base}")

    def test_translations_are_judged_equivalent_to_their_source(self):
        stride = max(1, len(self.pairs) // SAMPLES)
        sample = self.pairs[::stride][:SAMPLES]

        matched_source, matched_translation = self.pairs[0]
        _other_source, foreign_translation = self.pairs[-1]
        _progress(
            SUITE, f"System One: calibrating on 2 controls, judging {len(sample)}"
        )
        matched = ask(
            self.base, self.key, matched_source, matched_translation, self.model
        )
        mismatched = ask(
            self.base, self.key, matched_source, foreign_translation, self.model
        )
        self.assertGreaterEqual(
            matched - mismatched,
            MIN_SEPARATION,
            f"System One answered {matched} for a translation of its own source "
            f"and {mismatched} for one belonging to another entry, a spread "
            f"below {MIN_SEPARATION}. It is not telling the two apart, so its "
            "verdict on the sample carries no information.",
        )

        offenders: list[str] = []
        for index, (source, translation) in enumerate(sample, start=1):
            score = ask(self.base, self.key, source, translation, self.model)
            _progress(SUITE, f"System One: [{index}/{len(sample)}] noul={score:.4f}")
            if score <= mismatched:
                offenders.append(
                    f"{score:.4f} (mismatched control {mismatched:.4f}): "
                    f"{source[:60]!r} -> {translation[:60]!r}"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} of {len(sample)} sampled translations scored "
                "no better than a translation taken from another entry:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )
