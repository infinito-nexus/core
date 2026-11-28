"""The OpenAPI description the orchestrator serves at ``/openapi.json``."""

from __future__ import annotations

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Agent Orchestrator", "version": "1.0.0"},
    "paths": {
        "/health": {"get": {"summary": "Liveness probe"}},
        "/status": {"get": {"summary": "Control-plane status"}},
        "/routines": {"get": {"summary": "Routines of the deployed revision"}},
        "/routines/run": {"post": {"summary": "Start a routine run"}},
        "/routines/hold": {"post": {"summary": "Owner hold on a routine"}},
        "/routines/lift": {"post": {"summary": "Lift an owner hold"}},
        "/routines/block": {"post": {"summary": "Record an owner-only blocker"}},
        "/routines/clear": {"post": {"summary": "Clear an owner-only blocker"}},
        "/ci/slot": {"post": {"summary": "Request a repository's CI slot"}},
        "/ci/release": {"post": {"summary": "Release a repository's CI slot"}},
        "/audit": {"get": {"summary": "Audit chain head and verification"}},
        "/webhooks/{provider}": {"post": {"summary": "Provider webhook intake"}},
        "/instances/register": {"post": {"summary": "Register a detached instance"}},
        "/channels/dispatch": {"post": {"summary": "Dispatch a channel message"}},
    },
}
