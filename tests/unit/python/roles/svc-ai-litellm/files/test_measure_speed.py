"""The deploy measures a rate per model, because no catalogue carries one.

Speed is a property of this machine under this load, not of the model, so the
numbers the router ranks on come from requests the deploy actually sent. These
cases pin what the script does with them: it measures only a model that has no
rate yet, discards the cold first sample, takes a median rather than a mean,
refuses to rewrite a rate that barely moved, and never drops a model because
one deploy could not reach it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from typing import ClassVar, Self
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/python/measure_speed.py"

SAMPLE_TIMEOUT = 60.0
WARMUP_TIMEOUT = 240.0

ENVIRONMENT = {
    "LITELLM_MK": "sk-master-key",
    "LITELLM_PORT": "4000",
    "LITELLM_SAMPLES": "12",
    "LITELLM_TIMEOUT": str(SAMPLE_TIMEOUT),
    "LITELLM_WARMUP": str(WARMUP_TIMEOUT),
    "LITELLM_EXCLUDE": "auto",
    "LITELLM_REMEASURE": "",
    "LITELLM_PREVIOUS": "{}",
}


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class Gateway:
    """A gateway that answers /v1/models and bills each completion a duration.

    Args:
        served: the model ids /v1/models publishes.
        durations: model -> the seconds each successive call takes; the last
            value repeats once the list runs out.
        tokens: completion tokens every answer reports.
    """

    def __init__(self, served, durations, tokens=60) -> None:
        self.served = served
        self.durations = durations
        self.tokens = tokens
        self.clock = 0.0
        self.calls: dict[str, int] = {}
        self.timeouts: dict[str, list[float]] = {}

    def urlopen(self, request, timeout=None) -> FakeResponse:
        if request.full_url.endswith("/v1/models"):
            return FakeResponse(
                json.dumps({"data": [{"id": name} for name in self.served]}).encode()
            )
        model = json.loads(request.data.decode())["model"]
        index = self.calls.get(model, 0)
        self.calls[model] = index + 1
        self.timeouts.setdefault(model, []).append(timeout)
        schedule = self.durations[model]
        self.clock += schedule[min(index, len(schedule) - 1)]
        return FakeResponse(
            json.dumps({"usage": {"completion_tokens": self.tokens}}).encode()
        )

    def monotonic(self) -> float:
        return self.clock


def run(gateway, **environment):
    """The script against *gateway*, returning the JSON it printed."""
    spec = importlib.util.spec_from_file_location("measure_speed", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict("os.environ", {**ENVIRONMENT, **environment}, clear=False),
        patch("urllib.request.urlopen", gateway.urlopen),
        patch("time.monotonic", gateway.monotonic),
        redirect_stdout(io.StringIO()) as captured,
    ):
        spec.loader.exec_module(module)
        module.main()
    return json.loads(captured.getvalue())


class TestMeasureSpeed(unittest.TestCase):
    def test_a_rate_is_output_tokens_over_the_wall_clock(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        self.assertEqual(run(gateway)["m"], 30.0)

    def test_it_sends_the_configured_number_of_requests(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]})
        run(gateway, LITELLM_SAMPLES="12")
        self.assertEqual(gateway.calls["m"], 12)

    def test_the_cold_first_sample_is_discarded(self) -> None:
        gateway = Gateway(["m"], {"m": [600.0, 2.0]}, tokens=60)
        self.assertEqual(
            run(gateway)["m"],
            30.0,
            "a backend pays its load cost on the first call, which is not the "
            "rate any later caller sees",
        )

    def test_the_cold_first_sample_gets_the_longer_budget(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        run(gateway)
        self.assertEqual(
            gateway.timeouts["m"][:2],
            [WARMUP_TIMEOUT, SAMPLE_TIMEOUT],
            "the cold call pays the model load, so holding it to the sample "
            "budget would time out exactly the models worth measuring",
        )

    def test_one_slow_sample_does_not_move_the_median(self) -> None:
        schedule = [600.0] + [2.0] * 5 + [120.0] + [2.0] * 5
        gateway = Gateway(["m"], {"m": schedule}, tokens=60)
        self.assertEqual(run(gateway)["m"], 30.0)

    def test_a_single_sample_keeps_its_own_measurement(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        self.assertEqual(
            run(gateway, LITELLM_SAMPLES="1")["m"],
            30.0,
            "discarding the only sample would return nothing; at this setting "
            "the number is worth less than the proof that the path ran",
        )

    def test_the_router_alias_is_not_measured(self) -> None:
        gateway = Gateway(["auto", "m"], {"m": [2.0]})
        self.assertEqual(list(run(gateway)), ["m"])

    def test_every_served_model_gets_its_own_rate(self) -> None:
        gateway = Gateway(["slow", "fast"], {"slow": [6.0], "fast": [1.0]}, tokens=60)
        self.assertEqual(run(gateway), {"slow": 10.0, "fast": 60.0})


class TestOnlyUnrankedIsMeasured(unittest.TestCase):
    """The traffic is the live surface, so a stored rate sends none of it."""

    STORED: ClassVar[dict] = {"m": 31.0}

    def test_a_model_that_already_has_a_rate_is_not_measured(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        measured = run(gateway, LITELLM_PREVIOUS=json.dumps(self.STORED))
        self.assertEqual(gateway.calls.get("m", 0), 0)
        self.assertEqual(measured["m"], 31.0)

    def test_an_unranked_model_beside_a_ranked_one_is_measured(self) -> None:
        gateway = Gateway(["m", "new"], {"m": [2.0], "new": [1.0]}, tokens=60)
        measured = run(gateway, LITELLM_PREVIOUS=json.dumps(self.STORED))
        self.assertEqual(gateway.calls.get("m", 0), 0)
        self.assertEqual(measured, {"m": 31.0, "new": 60.0})

    def test_the_remeasure_switch_sends_the_requests_again(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        run(gateway, LITELLM_PREVIOUS=json.dumps(self.STORED), LITELLM_REMEASURE="1")
        self.assertEqual(gateway.calls["m"], 12)


class TestRemeasuring(unittest.TestCase):
    """Only a re-measurement can move a stored number, and barely moving does not."""

    def remeasure(self, gateway, stored):
        return run(gateway, LITELLM_PREVIOUS=json.dumps(stored), LITELLM_REMEASURE="1")

    def test_a_rate_within_tolerance_keeps_the_stored_number(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        self.assertEqual(
            self.remeasure(gateway, {"m": 31.0})["m"],
            31.0,
            "an unclamped result rewrites the config and restarts the gateway "
            "on every deploy, because no two runs measure the same machine",
        )

    def test_a_rate_beyond_tolerance_replaces_the_stored_number(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=60)
        self.assertEqual(self.remeasure(gateway, {"m": 10.0})["m"], 30.0)

    def test_a_model_that_cannot_be_reached_keeps_its_stored_rate(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]})
        listing = gateway.urlopen

        def refuse(request, timeout=None):
            if request.full_url.endswith("/v1/models"):
                return listing(request, timeout)
            raise OSError("connection refused")

        gateway.urlopen = refuse
        self.assertEqual(
            self.remeasure(gateway, {"m": 12.5})["m"],
            12.5,
            "one bad minute must not unrank a model against its peers",
        )

    def test_a_model_that_answers_no_tokens_is_left_unranked(self) -> None:
        gateway = Gateway(["m"], {"m": [2.0]}, tokens=0)
        self.assertEqual(run(gateway), {})


if __name__ == "__main__":
    unittest.main()
