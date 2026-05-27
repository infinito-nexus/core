# CLI README 📄

This page covers `README.md` files stored inside `cli/` category folders (directories under `cli/` that group sub-commands but do not themselves contain a `__main__.py`).
For general documentation rules such as links, writing style, RFC 2119 keywords, and emoji placement, see [documentation.md](../../../documentation.md).

## Purpose 🎯

A CLI category folder MAY contain a `README.md` that describes the category.
The first paragraph of that file is read by the CLI help system ([help.py](../../../../../cli/core/help.py)) and surfaced as the category's one-line description in `infinito --help`, `infinito <category>`, and `infinito --tree`.

## Scope 📋

A CLI `README.md` MUST stay focused on what kind of sub-commands the category groups.
A CLI `README.md` MUST NOT list the sub-commands themselves, because the CLI help system already does that automatically.
A CLI `README.md` MUST NOT describe individual sub-command flags or option signatures, because each runnable sub-command exposes its own argparse `--help`.

## Structure 📐

A CLI `README.md` MUST contain at least an H1 title and one description paragraph.
Further sections are OPTIONAL and MAY be added when contributors need extra context that does not belong in the runtime help.

### 1. Title (required) 🏷️

The H1 heading MUST be the human-readable name of the category, ending with a single trailing emoji that hints at the topic.

```markdown
# Administration 🛠️
```

### 2. Description (required) 📖

A single paragraph (one or two sentences) immediately below the H1.
It MUST explain what kind of commands live in the directory.
It MUST NOT name the sub-commands explicitly.
It MUST stand on its own when extracted by the CLI help system, which collapses multi-line paragraphs into a single line.

```markdown
# Administration 🛠️

Operator-facing tooling for provisioning inventories, running dedicated deploys, and managing host secrets.
```

### 3. Further sections (optional) ➕

Additional sections (for example "When to use", "Conventions", "Background") MAY follow the description paragraph.
They MUST be separated from the description paragraph by a blank line so the help-extraction heuristic stops at the right place.
They MUST NOT duplicate content that the sub-commands' own `--help` output already exposes.

## Formatting Rules 📏

- The H1 emoji MUST come after the title text, not before it.
- The description paragraph MUST be a single paragraph (no blank lines inside it).
- Link text MUST follow the link rules in [documentation.md](../../../documentation.md).
- Body text MAY use emojis when they aid readability.

## Runnable sub-commands ⚙️

Sub-commands inside a category folder (directories with their own `__main__.py`) MUST NOT carry a `README.md`.
Their description is taken from the argparse `description=` argument that the help system reads via `python -m <module> --help`.
For an example see [help.py](../../../../../cli/core/help.py).
