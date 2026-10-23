"""The failures the gateway answers with rather than hides."""

from __future__ import annotations


class GatewayError(Exception):
    """Base of every failure the gateway reports to its caller."""


class NoBackendError(GatewayError):
    """No engine could answer.

    The gateway never falls back to returning the source text: a caller that
    receives its own string back, with a 200 and no marker, stores it as a
    translation and the mistake outlives every later fix.
    """


class MangledTermError(GatewayError):
    """An engine returned an answer that lost a glossary term.

    Rejected rather than cached: a cached answer with a mangled term is
    served again long after the engine that produced it was replaced.
    """


class EngineRefusedError(GatewayError):
    """One engine failed. Counted apart from losing a comparison.

    Failing is not the same as answering worse. An engine that errors drops
    out of the candidate set without its loss being written to the learning
    log, so an outage does not teach the router that the engine is bad.
    """
