"""Score every sampled translation against its source on a named scale.

``test_system_one.py`` asks one yes-or-no question about one language and
reads the answer as an ordering against two controls, because a bare ``noul``
probability carries this deployment's calibration and a fixed threshold on it
would encode that calibration into the suite.

A ``score`` question does not have that problem: the levels are written out,
the judge answers with an index over them, and "below the middle level" means
what the middle level says it means rather than what this deployment's
probabilities happen to look like. That is what lets this check cover every
language instead of one, and fail on a named level instead of on a spread.

The judge is a chat model reached through the model gateway, not ``laya``.
Measured against the fixture below, ``laya``'s ``english`` checkpoint
separates a faithful rendering from an unrelated text in 17 of 47 languages
and its ``multilingual`` checkpoint in none, answering around 1.5 either way.
Routing a checkpoint per language was the previous answer and it is gone:
``meta/languages.yml`` carries identity only, and one judge covers every
language the catalogs hold.

The control is a known-answer fixture, not two catalog entries. It is
rendered by the gateway, the same path ``cli/build/i18n`` fills the catalogs
through, and not by the LibreTranslate engine behind it: the engine declares
a fraction of the table, so asking it for the fixture excluded every language
the gateway reaches through its chat backend, which is most of them. Those
are the languages worth watching, because a gap there means that backend is
absent or failing rather than that the language is unreachable.

The gateway renders one fixed English sentence and one unrelated English
sentence into the target language, and the language is judged only when the
rendering
scores at or above the middle level while the unrelated text scores below it.
Both legs are required: a catalog-derived mismatch is one-sided, so a judge
answering at the bottom of the scale for everything passes it and then
reports every sample as an offender, and in a language the judge cannot read
at all the two entries pass it on the technical tokens they share. A language
whose control does not separate is reported as unjudged rather than as an
offender, which is what ``tests/oracle/__init__.py`` means by declaring a run
inconclusive instead of letting it return green.

Context is thin on purpose for now: an entry's catalog and domain identify it,
but the file it was extracted from does not reach here, because
``utils/i18n/catalog.py`` builds the template without locations and the
catalogs therefore carry none. Naming the source file in the question would
mean changing extraction and rewriting every catalog, which is its own change.
"""

from __future__ import annotations

import unittest

from tests.utils.services import answers as serves
from tests.utils.services import progress as _progress
from utils.cache.yaml import load_yaml
from utils.i18n.catalog import catalog_path, is_machine_translation, read_catalog
from utils.i18n.judge import MIDDLE, ChatJudge
from utils.i18n.languages import DOMAINS, domain_languages, load_languages
from utils.i18n.libretranslate import GATEWAY_ROLE, GATEWAY_SERVICE_KEY
from utils.i18n.spans import prose
from utils.inventory.tools import LITELLM_KEY, lane_url
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT, SUITE

JUDGE_ROLE = "svc-ai-litellm"
JUDGE_SERVICE_KEY = "litellm"
JUDGE_SERVICES_FILE = PROJECT_ROOT / "roles" / JUDGE_ROLE / ROLE_FILE_META_SERVICES
SAMPLES_PER_LANGUAGE = 12
MAX_REFUSED_SHARE = 0.02
MIN_SOURCE_CHARS = 40
ENGINE_WORKERS = 1
FIXTURE_SOURCE = (
    "The nightly backup keeps seven daily copies and runs at two o'clock in "
    "the morning."
)
FIXTURE_UNRELATED = (
    "The small bakery near the station closes early on Saturday afternoon."
)


def _model() -> str:
    """Return the alias the model gateway resolves the judge's prompt with."""
    return load_yaml(JUDGE_SERVICES_FILE)[JUDGE_SERVICE_KEY]["router"]["alias"]


def _pairs(code: str, domain: str) -> list[tuple[str, str]]:
    """Return machine-translated (source, translation) pairs worth judging.

    Args:
        code: ISO 639-1 code of the catalog.
        domain: catalog domain.
    """
    path = catalog_path(PROJECT_ROOT, code, domain)
    if not path.is_file():
        return []
    return [
        (str(m.id), str(m.string))
        for m in read_catalog(path)
        if m.id
        and m.string
        and any(is_machine_translation(c) for c in m.user_comments or [])
        and len(prose(str(m.id)).strip()) >= MIN_SOURCE_CHARS
    ]


class TestTranslationScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = lane_url(PROJECT_ROOT, JUDGE_ROLE, JUDGE_SERVICE_KEY)
        cls.gateway = lane_url(PROJECT_ROOT, GATEWAY_ROLE, GATEWAY_SERVICE_KEY)
        for url in (f"{cls.base}/health/liveliness", f"{cls.gateway}/languages"):
            if not serves(url):
                raise unittest.SkipTest(
                    f"nothing answers on {url}. `make test-oracle` brings the "
                    "tools lane up before the suite runs, and this check cannot "
                    "deploy it from inside the stack's container."
                )
        _progress(SUITE, f"the judge answers on {cls.base}")

    def _unreadable(self, client, judge, available: set[str], code: str) -> str:
        """Return why the judge cannot be trusted on this language.

        Args:
            client: the gateway the fixture is rendered with.
            judge: the model asked to place a pair on the levels.
            available: the target codes that gateway serves.
            code: ISO 639-1 code of the language to judge.

        Returns:
            Empty when the judge separates the fixture from an unrelated text,
            so its verdicts on this language's samples carry information.
        """
        if client.server_code(code) not in available:
            return "the gateway does not render the fixture into this language"
        values = client.translate([FIXTURE_SOURCE, FIXTURE_UNRELATED], code).values
        if not all(isinstance(value, str) and value for value in values):
            return f"the gateway rendered no usable fixture: {values!r}"
        faithful, unrelated = values
        kept = judge.score(FIXTURE_SOURCE, faithful)
        other = judge.score(FIXTURE_SOURCE, unrelated)
        if kept < MIDDLE:
            return (
                f"a faithful rendering of the fixture scored {kept}, below the "
                f"middle level {MIDDLE}"
            )
        if other >= MIDDLE:
            return (
                f"an unrelated text scored {other}, at or above the middle "
                f"level {MIDDLE}"
            )
        name = self.names.get(code, code)
        reads = judge.speaks(faithful, name)
        english = judge.speaks(FIXTURE_UNRELATED, name)
        if reads < MIDDLE:
            return (
                f"the gateway's own rendering was placed at {reads} on being "
                f"written in {name}, below the middle level {MIDDLE}"
            )
        if english >= MIDDLE:
            return (
                f"an English sentence was placed at {english} on being written "
                f"in {name}, at or above the middle level {MIDDLE}"
            )
        return ""

    def test_every_sampled_translation_carries_its_source(self):
        from utils.i18n.client import LibreTranslate

        client = LibreTranslate(self.gateway, ENGINE_WORKERS)
        available = client.targets()
        judge = ChatJudge(self.base, _model(), api_key=LITELLM_KEY)
        languages = load_languages(PROJECT_ROOT)
        self.names = {
            code: str(entry.get("name", code)) for code, entry in languages.items()
        }
        verdicts: dict[str, str] = {}
        offenders: list[str] = []
        refused: list[str] = []
        judged = 0

        for domain in DOMAINS:
            for code in domain_languages(languages, domain):
                pairs = _pairs(code, domain)
                if not pairs:
                    continue
                where = f"{domain}/{code}"
                if code not in verdicts:
                    verdicts[code] = self._unreadable(client, judge, available, code)
                    _progress(
                        SUITE,
                        f"{code}: {verdicts[code] or 'the judge separates the fixture'}",
                    )
                if verdicts[code]:
                    continue

                stride = max(1, len(pairs) // SAMPLES_PER_LANGUAGE)
                sample = pairs[::stride][:SAMPLES_PER_LANGUAGE]
                _progress(SUITE, f"scoring {len(sample)} samples of {where}")
                name = self.names.get(code, code)
                for source, translation in sample:
                    try:
                        level = judge.score(source, translation)
                    except ValueError as exc:
                        refused.append(f"{where}: {exc}")
                        continue
                    judged += 1
                    if level < MIDDLE:
                        offenders.append(
                            f"{where}: {level} below the middle level {MIDDLE}: "
                            f"{source[:60]!r} -> {translation[:60]!r}"
                        )
                        continue
                    written = prose(translation).strip()
                    if len(written) < MIN_SOURCE_CHARS:
                        continue
                    try:
                        spoken = judge.speaks(written, name)
                    except ValueError as exc:
                        refused.append(f"{where}: {exc}")
                        continue
                    if spoken < MIDDLE:
                        offenders.append(
                            f"{where}: states its source but was placed at "
                            f"{spoken} on being written in {name}: "
                            f"{translation[:60]!r}"
                        )

        unjudged = {code: why for code, why in sorted(verdicts.items()) if why}
        if not judged:
            self.fail(
                f"no sample reached a verdict: the judge read none of the "
                f"{len(verdicts)} language(s) the catalogs hold machine "
                "translations for, so a green result would mean nothing:\n"
                + "\n".join(f"  - {code}: {why}" for code, why in unjudged.items())
            )
        if offenders:
            self.fail(
                f"{len(offenders)} of {judged} sampled translations state "
                "something other than their source:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )
        if len(refused) > judged * MAX_REFUSED_SHARE:
            self.fail(
                f"the judge named no level for {len(refused)} sample(s) "
                f"against {judged} it judged, so the green rests on too "
                "little:\n" + "\n".join(f"  - {r}" for r in refused[:20])
            )
        _progress(
            SUITE,
            f"{judged} sampled translations carry their source in "
            f"{len(verdicts) - len(unjudged)} language(s) the judge reads, "
            f"{len(unjudged)} it does not, {len(refused)} it would not answer",
        )
