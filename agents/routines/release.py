"""Release routine: turn one changelog entry into every announcement of a
release. Deterministic steps extract the version jumps and contributors, read
the changelog once into the brief, outline the investor sections and render
the design theme; model steps write the entry prose, the brief's benefits and
one text per channel from the brief only; the deterministic check gates the
hand-over, and the operator publishes.
"""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

RELEASE_DIR = "<release dir>"
CHANGELOG_DIR = f"{RELEASE_DIR}/changelog"

STEPS = [
    Step(
        "T1",
        f"Operator asks for the announcements of a release; {RELEASE_DIR} is /tmp/release-<version>",
        "trigger",
        nxt="entry",
    ),
    Step(
        "entry",
        "Does CHANGELOG.md carry the entry of <version>?",
        "decision",
        branches=(("✅ yes", "brief"), ("❌ no", "facts")),
    ),
    Step(
        "facts",
        f"python -m cli.contributing.changelog.extract facts --head <ref> --out {CHANGELOG_DIR}: net version jumps and contributors",
        nxt="prose",
    ),
    Step(
        "prose",
        f"Write {CHANGELOG_DIR}/entry.md around jumps.md and contributors.md: Breaking, Added, Changed, Fixed, Upgrade notes and each contributor's areas, no number the commits lack",
        "model",
        nxt="insert",
    ),
    Step(
        "insert",
        f"python -m cli.contributing.changelog.extract insert --entry {CHANGELOG_DIR}/entry.md --out {CHANGELOG_DIR}: scratch CHANGELOG.md, markdownlint green",
        nxt="brief",
    ),
    Step(
        "brief",
        f"python -m cli.contributing.release brief --version <version> --dir {RELEASE_DIR} [--changelog {CHANGELOG_DIR}/lint/CHANGELOG.md]: the changelog read once into brief.yml",
        nxt="languages",
    ),
    Step(
        "languages",
        "Ask once which languages to write, English by default, and set brief.yml languages",
        "ask",
        nxt="benefits",
    ),
    Step(
        "benefits",
        "Fill brief.yml: the headline benefit and three to five benefits, each citing its changelog lines verbatim",
        "model",
        nxt="outline",
    ),
    Step(
        "outline",
        f"python -m cli.contributing.release outline --dir {RELEASE_DIR} [--facts <facts file>]: the investor sections the brief or the facts prove",
        nxt="theme",
    ),
    Step(
        "theme",
        f"python -m utils.design.film_theme --template <template> --out {RELEASE_DIR}/<image>.<language>.svg for the banner and the Instagram image",
        nxt="article",
    ),
    Step(
        "article",
        "From brief.yml only: article.<language>.html, the banner text and banner-alt.<language>.txt",
        "model",
        nxt="linkedin",
    ),
    Step(
        "linkedin",
        "From brief.yml only: linkedin-article.<language>.md and linkedin-post.<language>.txt",
        "model",
        nxt="mastodon",
    ),
    Step(
        "mastodon",
        "From brief.yml only: mastodon.<language>.txt",
        "model",
        nxt="whatsapp",
    ),
    Step(
        "whatsapp",
        "From brief.yml only: whatsapp-channel.en.txt and whatsapp-message.de.txt",
        "model",
        nxt="newsletter",
    ),
    Step(
        "newsletter",
        "From brief.yml only: newsletter-<audience>.<language>.md for investors, customers and developers; the investor one holds only investor-outline.yml's sections",
        "model",
        nxt="instagram",
    ),
    Step(
        "instagram",
        "From brief.yml only: the Instagram image text and instagram-caption.<language>.txt",
        "model",
        nxt="render",
    ),
    Step(
        "render",
        "Screenshot every filled .svg to its .png with the headless shell at the image's own size, then look at each",
        nxt="check",
    ),
    Step(
        "check",
        f"python -m cli.contributing.release check --dir {RELEASE_DIR} [--facts <facts file>] clean? (placeholders, em dashes, channel bounds, numbers against the brief)",
        "decision",
        branches=(("✅ clean", "handover"), ("❌ findings", "revise")),
    ),
    Step("revise", "Fix each finding in the file it names", "model", nxt="check"),
    Step(
        "handover",
        f"Hand over every file of {RELEASE_DIR}/ and where it goes; nothing is published, the operator publishes",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("release", STEPS)
