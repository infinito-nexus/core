# Documentation 📝

All project documentation MUST be reachable at [docs.infinito.nexus](https://docs.infinito.nexus/).

## Comments 💬

- You SHOULD write code so it is logical and self-explanatory and usually does not need comments.
- You MUST add code comments only when an exception, edge case, or surprising decision would otherwise confuse readers.
- You MUST use comments to explain why something is unusual, not to restate what obvious code already does.
- When keeping an intentionally retained outdated version pin, you MUST document the exception at the pin site with a local `TODO` comment in the file's normal comment style (`#todo`, `# TODO`, or similar) and explain why it remains pinned so the root cause stays visible until it can be fixed.

## Requirement Keywords (RFC 2119) 📋

You MUST use [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) keywords in all documentation to express requirement levels unambiguously:

| Keyword | Meaning |
|---|---|
| `MUST` / `REQUIRED` / `SHALL` | Absolute requirement. No deviation allowed. |
| `MUST NOT` / `SHALL NOT` | Absolute prohibition. Never do this. |
| `SHOULD` / `RECOMMENDED` | Strongly recommended. Deviation requires justification. |
| `SHOULD NOT` / `NOT RECOMMENDED` | Strongly discouraged. Allowed only with justification. |
| `MAY` / `OPTIONAL` | Permitted but not required. |

## Links 🔗

- You MUST NOT use the full URL as link text. Use the domain name, `here`, or the filename instead. Never use the full path.
- After `See`, you MUST use the domain name as link text, not `here`. `here` is only acceptable when the surrounding sentence reads naturally with it (e.g. "More information [here](...)").
- For communication links such as Matrix, email, or phone, you MUST show only the value itself as link text, without any protocol prefix or URL wrapper.

| Type | MUST NOT | MUST |
|---|---|---|
| Web link | `https://docs.infinito.example/` | `docs.infinito.example`, `here`, a descriptive label, or `setup.md` |
| File link | `docs/contributing/workflow.md` | `workflow.md` or `Contribution Flow` |
| Email | `mailto:hello@infinito.nexus` | `hello@infinito.nexus` |
| Matrix | `[#room:infinito.nexus](https://some-url.example/)` | `@user:infinito.nexus` |
| Phone | `tel:+491234567890` | `+49 123 456 7890` |

## Semantics and Writing ✍️

- You MUST keep code and comments in English.
- You MUST fix nearby wording and semantic issues when you touch a file, and correct obvious nearby issues proactively in the same pass.
- You SHOULD use emojis when they make the text more visually appealing, improve the mood, and increase readability.
- You MUST NOT use em dashes (—) as thought breaks or clause separators. You SHOULD prefer complete sentences. Hyphens (-) MAY be used for compound words and list items.
- You MUST NOT explicitly declare a documentation page as "the SPOT", "Single Point of Truth", or any equivalent self-label. SPOT status is conferred by readers cross-linking to the page from elsewhere, not by the page asserting it about itself. Describe the subject directly instead.
- You MUST describe only the current state of the subject. You MUST NOT carry historical context, migration notes, or comparisons to former implementations into documentation. Phrases such as "this replaces X", "previously X did Y", "formerly known as X", "the legacy X", or "after the refactor" MUST NOT appear in documentation. Readers arrive in the present and need to know how the subject works now, not how it used to work. Historical context belongs in commit messages, pull request descriptions, and changelogs, where it is anchored to a point in time and ages gracefully. Documentation that carries history rots as soon as the next refactor lands.

## Headlines 🏷️

- You SHOULD place emojis after the headline text to visually highlight headings and improve scannability.
- You MUST NOT place emojis before the headline text, as this interferes with heading hierarchy rendering in some tools.
- You MUST NOT add emojis to headlines in `docs/agents/` files, as these are machine-readable instruction files where emojis interfere with parsing.

## Documentation Structure 🗂️

### Role README 📄

See [readme_md.md](artefact/files/role/readme_md.md) for the requirement, required structure, section order, and formatting rules for role `README.md` files.

### Docs README 📄

See [Docs README](artefact/files/docs/readme_md.md) for the purpose, scope, and navigation rules for `README.md` files stored inside `docs/` directories.

### Markdown 📋
- You SHOULD prefer `README.md` for directory-level documentation when a human-facing entry point already exists.
- You MUST keep core information inside the repository, either in code or in `.md` files.
- You MUST use `.md` files for commands, workflows, setup, and contributor guidance.
- You MUST NOT use `.md` files to describe implementation logic that is already visible in the code.

### Sphinx 📚

- The root `index.rst` uses a `:glob:` toctree (`docs/**`) to automatically include every documentation page.
- Sphinx indexing SHOULD happen automatically through that root `:glob:` toctree.
- You SHOULD avoid creating or maintaining manual per-directory indexes when automatic indexing already covers the same pages.
  An additional `index.rst` inside a `docs/` subdirectory is NOT RECOMMENDED because the root index already covers those pages automatically, but it MAY be added when a focused local entry point materially improves navigation.
  If such a local `index.rst` is added, it SHOULD stay minimal and MUST NOT duplicate a manually curated page inventory that the automatic index already provides.
- You MUST keep cross-links between `.md` files up to date so readers can navigate between related pages.
