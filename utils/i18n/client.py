"""HTTP client for the LibreTranslate API.

SERVER_CODES maps the catalog's bare ISO 639-1 codes onto the script-qualified
names LibreTranslate serves some languages under. A code missing from it never
turns up in /languages, and the readiness wait then spins until its timeout.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.i18n.languages import SOURCE_LANGUAGE
from utils.i18n.limits import BATCH_SIZE
from utils.i18n.placeholders import Rejected, mask, unmask
from utils.i18n.untranslatable import untranslatable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

SERVER_CODES = {"zh": "zh-Hans"}
POLL_SECONDS = 5
PROGRESS_SECONDS = 30
OUTSTANDING_SHOWN = 12


def _outstanding(missing: set[str], catalog_of: dict[str, str]) -> str:
    """Return the catalog codes still missing, shortened to stay one line.

    Args:
        missing: the server codes the server does not offer yet.
        catalog_of: server code to the catalog code the operator knows it by.
    """
    codes = sorted(catalog_of[code] for code in missing)
    shown = " ".join(codes[:OUTSTANDING_SHOWN])
    rest = len(codes) - OUTSTANDING_SHOWN
    return f"{shown} +{rest}" if rest > 0 else shown or "none"


REQUEST_TIMEOUT_SECONDS = 600
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2


@dataclass(frozen=True)
class Outcome:
    """What one translation call produced, and why anything is missing.

    Deliberately not a tuple: a caller that forgets ``.values`` would
    otherwise zip against the four fields instead of the translations.

    Args:
        values: one entry per source: the translation, a ``Rejected`` carrying
            what came back and why it was turned down, or None when the server
            never answered.
        refused: requests the server turned down, retries included.
        damaged: translations that altered a protected span.
        refusal: the last refusal's message, empty when none happened.
    """

    values: list[str | Rejected | None]
    refused: int
    damaged: int
    refusal: str


def merge(outcomes: Iterable[Outcome]) -> Outcome:
    """Fold per-text outcomes back into one for the whole batch."""
    values: list[str | Rejected | None] = []
    refused = damaged = 0
    refusal = ""
    for outcome in outcomes:
        values += outcome.values
        refused += outcome.refused
        damaged += outcome.damaged
        refusal = outcome.refusal or refusal
    return Outcome(values, refused, damaged, refusal)


class LibreTranslate:
    """Client for the LibreTranslate HTTP API.

    Args:
        url: base URL of the server.
        workers: parallel translation requests.
    """

    def __init__(self, url: str, workers: int, batch_size: int = BATCH_SIZE):
        self.url = url.rstrip("/")
        self.workers = workers
        self.batch_size = batch_size

    def _call(self, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - the URL is the LibreTranslate container this process started
            f"{self.url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(  # noqa: S310 - the URL is the LibreTranslate container this process started
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return json.load(response)

    @staticmethod
    def server_code(code: str) -> str:
        """Return the target code the server knows this catalog code by."""
        return SERVER_CODES.get(code, code)

    def targets(self) -> set[str]:
        """Return the languages the server translates English into."""
        for language in self._call("/languages"):
            if language["code"] == SOURCE_LANGUAGE:
                return set(language["targets"])
        return set()

    def wait(
        self,
        codes: list[str],
        timeout: float,
        status: Callable[[], str] | None = None,
    ) -> None:
        """Block until the server translates into every language of ``codes``.

        Args:
            codes: required target languages.
            timeout: seconds to wait before giving up.
            status: returns one line about the server's own progress, reported
                every ``PROGRESS_SECONDS`` while it installs its models. The
                server offers no endpoint before it is ready, so without this
                the wait is indistinguishable from a hang for its whole hour.
        """
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        catalog_of = {self.server_code(code): code for code in codes}
        wanted = set(catalog_of)
        missing = set(wanted)
        answered = False
        spoken = 0.0
        while True:
            try:
                missing = wanted - self.targets()
                answered = True
                if not missing:
                    return
            except (OSError, ValueError):
                answered = False
            now = time.monotonic()
            if now - spoken >= PROGRESS_SECONDS:
                spoken = now
                extra = f", {status()}" if status else ""
                print(
                    f"LibreTranslate at {self.url}: "
                    f"{len(wanted) - len(missing)}/{len(wanted)} ready"
                    f"{'' if answered else ' (server silent)'}, "
                    f"pending {_outstanding(missing, catalog_of)}, "
                    f"waited {int(now - started)}s of {int(timeout)}s{extra}",
                    flush=True,
                )
            if now > deadline:
                raise TimeoutError(
                    f"LibreTranslate at {self.url} does not offer {sorted(missing)}"
                )
            time.sleep(POLL_SECONDS)

    def _post(self, masked: list, target: str) -> list | None:
        """Return the server's translations, or None once the retries run out.

        The server refuses a share of the requests while every lane hammers it
        at once, and those refusals used to discard their entries for good.
        """
        refusals = 0
        refusal = ""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                result = self._call(
                    "/translate",
                    {
                        "q": [item.text for item in masked],
                        "source": SOURCE_LANGUAGE,
                        "target": self.server_code(target),
                        "format": "html",
                    },
                )["translatedText"]
            except (urllib.error.HTTPError, ValueError, KeyError, TypeError) as exc:
                refusals += 1
                refusal = f"{type(exc).__name__}: {exc}"
                result = None
            if isinstance(result, list) and len(result) == len(masked):
                return result, refusals, refusal
            time.sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
        return None, refusals, refusal

    def _batch(self, texts: list[str], target: str) -> Outcome:
        masked = [mask(text) for text in texts]
        result, refused, refusal = self._post(masked, target)
        if result is None:
            if len(texts) == 1:
                return Outcome([None], refused, 0, refusal)
            return merge(self._batch([text], target) for text in texts)
        values = [
            unmask(translated, item, text, target)
            for translated, item, text in zip(result, masked, texts, strict=True)
        ]
        damaged = sum(1 for text in values if isinstance(text, Rejected))
        return Outcome(values, refused, damaged, refusal)

    def translate(self, texts: list[str], target: str) -> Outcome:
        """Translate ``texts`` from English into ``target``.

        Args:
            texts: source messages.
            target: ISO 639-1 code.

        Returns:
            One translation per source, ``None`` where it was discarded, plus
            the counts that say which of the two reasons applied. The counts
            belong to this call: lanes share the client, so a field on the
            client would mix another catalog's numbers into this one's.

        Raises:
            OSError: the server is unreachable; every further request would
                fail too, so the run stops instead of discarding the rest.
        """
        results: list[str | Rejected | None] = list(texts)
        wordy = [index for index, text in enumerate(texts) if not untranslatable(text)]
        size = self.batch_size
        batches = [wordy[i : i + size] for i in range(0, len(wordy), size)]
        refused = damaged = 0
        refusal = ""
        with ThreadPoolExecutor(self.workers) as pool:
            translated = pool.map(
                lambda batch: self._batch([texts[index] for index in batch], target),
                batches,
            )
            for batch, outcome in zip(batches, translated, strict=True):
                for index, text in zip(batch, outcome.values, strict=True):
                    results[index] = text
                refused += outcome.refused
                damaged += outcome.damaged
                refusal = outcome.refusal or refusal
        return Outcome(results, refused, damaged, refusal)
