from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, decide, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.gallery import GALLERY_COMMAND, MANIFEST_COMMAND, collect
from utils.cache.files import PROJECT_ROOT
from utils.design.gallery import GALLERY_ROOT, app_gallery
from utils.design.proposal import file_proposal
from utils.design.spec import DESIGN_ENTITY, SPEC_FILE, UI_PREFIXES

if TYPE_CHECKING:
    from collections.abc import MutableMapping

COMPOSE = "compose"
DEPLOYED = "🖼️ deployed"
NOTHING = "⏭️ nothing to capture"
CLEAN = "✨ clean"
PROPOSAL = "💡 proposal"
PROPOSE_COMMAND = "python -m cli.meta.roles.design.propose <app> --finding <text>"


def _scope(state: MutableMapping) -> MutableMapping:
    """Keep the apps a capture can reach under ``apps``.

    Args:
        state: reads ``apps`` (the application ids the green run deployed),
            ``disabled`` (the providers its ``disable=`` removed) and ``mode``
            (the deploy mode); keeps the ``web-app-`` and ``web-svc-`` apps
            with a design spec, none unless ``mode`` is ``compose`` and the
            design provider stayed on.
    """
    mode = state.get("mode") or ""
    design_off = DESIGN_ENTITY in (state.get("disabled") or [])
    reachable = mode == COMPOSE and not design_off
    apps = [
        app
        for app in state.get("apps") or []
        if reachable
        and app.startswith(UI_PREFIXES)
        and (PROJECT_ROOT / "roles" / app / SPEC_FILE).is_file()
    ]
    state["apps"] = apps
    inputs = {"mode": mode, "design_off": design_off, "apps": apps}
    return decide(state, "scope", inputs, DEPLOYED if apps else NOTHING)


def _propose(state: MutableMapping) -> MutableMapping:
    """File the review's findings of every captured app into the design queue.

    Args:
        state: reads ``findings`` (``{app: [finding, ...]}`` from the review)
            and ``apps``; a finding for an app outside ``apps`` is dropped;
            writes ``proposals`` as ``{app: proposal file}``.
    """
    captured = set(state.get("apps") or [])
    state["proposals"] = {
        app: str(file_proposal(app_gallery(GALLERY_ROOT, app), list(findings)))
        for app, findings in (state.get("findings") or {}).items()
        if app in captured
    }
    return state


STEPS = [
    Step(
        "scope",
        "Which web roles with a design spec did the green run leave on the compose stack with the design provider on? (none after disable=design or outside compose mode)",
        "decision",
        branches=((DEPLOYED, "capture"), (NOTHING, "done")),
        fn=_scope,
    ),
    Step(
        "capture",
        f"{GALLERY_COMMAND} per app, one at a time under the stack lock, no redeploy",
        nxt="manifest",
    ),
    Step(
        "manifest",
        f"{MANIFEST_COMMAND}: views per side, mode and viewport, views missing a shot",
        nxt="review",
        fn=collect,
    ),
    Step(
        "review",
        "Visual review against the palette, contrast and light and dark rules: what would a design pass change?",
        "model",
        branches=((CLEAN, "done"), (PROPOSAL, "propose")),
        output_schema=(("findings", dict),),
    ),
    Step(
        "propose",
        f"{PROPOSE_COMMAND} per change: written next to the gallery, make design-queue lists the role as proposed",
        nxt="done",
        fn=_propose,
    ),
    Step(
        "done",
        "Report the captured apps and the filed proposals; the role files stay untouched",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("tune_design", STEPS)
