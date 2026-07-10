# Caveman: Token Compression

[Caveman](https://github.com/JuliusBrussee/caveman) is a token-compression plugin installed via `make install-skills`. It reduces output token consumption through progressively terser communication styles. `make install-skills` copies the skills from the repository pinned as `INFINITO_SKILLS_REPOSITORY` in the generated `.env` (override via `custom.env`, see `docs/contributing/customize.md`); the [skills](https://github.com/kevinveenbirkenbach/skills) repository pins every skill in its `skills-lock.json` and also supports global installs via its own `make install`. This works universally across all supported agents: Claude Code, Codex, Gemini CLI, Cursor, Copilot, Windsurf, Cline, and more.

## Default Mode

Agents MUST operate in **`/caveman lite`** mode by default. Lite keeps grammar and readability intact while still reducing output size.

## Startup Notification

At the **start of every conversation**, before doing any other work, the agent MUST display the following block verbatim (substituting the active mode if it has been changed by the user):

```
[caveman: lite]  Switch: /caveman full · /caveman ultra · /caveman wenyan-lite · /caveman wenyan · /caveman wenyan-ultra · stop caveman
```

## Mode Reference

| Command | Style | Use when |
|---|---|---|
| `/caveman lite` | Professional brevity, grammar intact | Default: balanced readability |
| `/caveman full` | Fragment-based, drops articles | Context growing, prefer brevity |
| `/caveman ultra` | Maximally compressed, telegraphic | Context critical, every token counts |
| `/caveman wenyan-lite` | Classical Chinese, semi-formal | Alternative compression style |
| `/caveman wenyan` | Full classical Chinese terseness | Deep compression, classical style |
| `/caveman wenyan-ultra` | Extreme classical compression | Maximum reduction |
| `stop caveman` | Normal prose | User explicitly requests full output |

## Tier Progression: Token Budget Guidance

As the conversation grows, the agent MUST proactively suggest a higher tier. Base the estimate on observable signals: message count, response sizes, and whether context compression has been triggered by the system.

| Approximate token budget consumed | Action |
|---|---|
| < 20 % | Stay on current tier. No suggestion needed. |
| ≥ 20 % | Recommend upgrading from **lite → full** |
| ≥ 50 % | Recommend upgrading from **full → ultra** |
| ≥ 75 % | Strongly recommend **ultra** (or a wenyan variant); warn that context is running low |

Suggestions MUST be short, inline, and non-blocking. Example:

```
[caveman: lite | ~30 % context used → consider /caveman full]
```

The agent MUST NOT interrupt work to ask about tier changes. Recommendations appear as a single line at the start of the next response after the threshold is crossed.
