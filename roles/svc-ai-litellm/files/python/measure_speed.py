"""Measure how fast each served model generates, so the router can rank them.

The router scores a route on locality, price and speed. The first two are
declared or catalogued; speed has no source at all, because it is a property of
this machine under this load and not of the model. So it is measured here,
against the gateway that will serve the traffic.

Only a model without a stored rate is measured. A deploy that re-measured
everything would send requests whose results the tolerance below discards
anyway, and that traffic is the whole live surface of this script.

The result is a per-model median of output tokens per second, printed as JSON
for the deploy to store and render back into ``model_info.traits.speed``.

Environment:
    LITELLM_MK:        master key the gateway accepts.
    LITELLM_PORT:      port the gateway listens on inside its own container.
    LITELLM_SAMPLES:   requests per model; above one, the first is discarded.
    LITELLM_TIMEOUT:   seconds one measured request may take.
    LITELLM_WARMUP:    seconds the discarded first request may take.
    LITELLM_EXCLUDE:   comma-separated aliases to leave unranked, namely the
                       router's own and every mock. A mock generates nothing,
                       so its rate is the proxy's echo latency rather than a
                       model's, and ranking on it sends every request to a
                       fixture that answers the same string to anything.
    LITELLM_REMEASURE: non-empty to re-measure models that already have a rate.
    LITELLM_PREVIOUS:  the JSON of the last measurement.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

MASTER_KEY = os.environ["LITELLM_MK"]
PORT = os.environ["LITELLM_PORT"]
SAMPLES = int(os.environ["LITELLM_SAMPLES"])
TIMEOUT = float(os.environ["LITELLM_TIMEOUT"])
WARMUP_TIMEOUT = float(os.environ["LITELLM_WARMUP"])
EXCLUDE = {
    alias.strip()
    for alias in (os.environ.get("LITELLM_EXCLUDE") or "").split(",")
    if alias.strip()
}
REMEASURE = bool(os.environ.get("LITELLM_REMEASURE"))
PREVIOUS = json.loads(os.environ.get("LITELLM_PREVIOUS") or "{}")

LISTING_TIMEOUT = 30
MAX_TOKENS = 64
PROMPT = "Count from one to twenty in words."
TOLERANCE = 0.10


def call(path, payload=None, timeout=LISTING_TIMEOUT):
    """One gateway call, decoded.

    Args:
        path: the API path below the gateway root.
        payload: a mapping to POST, or None to GET.
        timeout: seconds the call may take.

    Returns:
        The decoded response body.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode() if payload else None,
        headers={
            "Authorization": f"Bearer {MASTER_KEY}",
            "Content-Type": "application/json",
        },
        method="POST" if payload else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 fixed internal http origin
        return json.loads(response.read())


def sample(model, timeout):
    """Output tokens per second for one request, or None if it yielded none."""
    started = time.monotonic()
    body = call(
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": MAX_TOKENS,
        },
        timeout,
    )
    elapsed = time.monotonic() - started
    tokens = (body.get("usage") or {}).get("completion_tokens") or 0
    if not tokens or elapsed <= 0:
        return None
    return tokens / elapsed


def measure(model):
    """The median rate over the samples, discarding the first as a cold load.

    A backend that has never answered this model pays its load cost on the
    first call, which is not the rate a later caller will see, and that call
    gets the longer budget for the same reason. The median then absorbs
    whatever else the machine was doing during one sample.

    A single-sample run keeps its one measurement rather than discarding it and
    returning nothing: at that setting the number is worth less than the proof
    that the path ran at all.
    """
    warmup = 1 if SAMPLES > 1 else 0
    rates = []
    for index in range(SAMPLES):
        cold = index < warmup
        rate = sample(model, WARMUP_TIMEOUT if cold else TIMEOUT)
        if rate is not None and not cold:
            rates.append(rate)
    return statistics.median(rates) if rates else None


def settled(model, measured):
    """The measurement, or the stored one when the move is within tolerance."""
    stored = PREVIOUS.get(model)
    if stored and abs(measured - stored) <= TOLERANCE * stored:
        return stored
    return round(measured, 2)


def rank(model):
    """This model's rate, measuring only when it has none to fall back on."""
    if model in PREVIOUS and not REMEASURE:
        print(f"KEPT {model}: {PREVIOUS[model]} tok/s", file=sys.stderr)
        return PREVIOUS[model]
    try:
        measured = measure(model)
    except (urllib.error.URLError, OSError, ValueError) as error:
        measured, why = None, type(error).__name__
    else:
        why = "no request produced output tokens"
    if measured is None:
        print(f"SKIPPED {model}: {why}", file=sys.stderr)
        return PREVIOUS.get(model)
    rate = settled(model, measured)
    print(f"MEASURED {model}: {rate} tok/s", file=sys.stderr)
    return rate


def main():
    served = [
        entry["id"]
        for entry in call("/v1/models").get("data") or []
        if entry.get("id") and entry["id"] not in EXCLUDE
    ]
    speeds = {}
    for model in served:
        rate = rank(model)
        if rate is not None:
            speeds[model] = rate
    print(json.dumps(speeds, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
