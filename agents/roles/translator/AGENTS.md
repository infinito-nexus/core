# Translator

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in [`SOUL.md`](SOUL.md).

- Machine translations go through `web-svc-translate`.
- A string reviewed by a human in Weblate is never overwritten; the translator only suggests.
- The translator runs the translation commands; no other routine does: `make i18n-extract`, `make i18n-prune`, `make i18n-translate`, `make i18n-retry` and `make i18n-tune`.
- Two entries of `agents/roles/translator/cron.yml` drive the translator:
  - Night (23:00 to 07:00 UTC): the window decides, not the load; translation runs or resumes at 23:00 regardless of load.
  - Day (07:00 to 23:00 UTC): a cron every 10 minutes measures host load. It starts or resumes translation when CPU is below 30 % and GPU is below 30 %, and pauses it when CPU is above 95 % or GPU is above 95 %.
- The day rule measures the load of everything except the translation lane itself (per-container figures, the rest of the system is the difference), so the translator's own load never stops it and the regulator cannot oscillate.
- On a host without a usable GPU (`accelerated()` in `utils/i18n/libretranslate.py` is false), the GPU condition counts as met.
- Pausing means `make i18n-pause`, which pauses the tools lane container; resuming means `make i18n-resume`. The lane keeps its loaded models, containers and connections, and continues exactly where it paused. Stopping the make process alone is never used, because the client keeps sending requests; stopping the lane container is never used, because it ends in a kill and costs a lane warm-up of about 25 minutes.
- A quality gate outranks both crons: while the machine's gate lock is held, the translator stays paused, at night as well, and resumes when the lock is released.
- At 07:00 UTC the night run pauses and the day rule takes over. A catalog is written only when it completes, so a pause never loses finished work, and `make i18n-translate` picks only empty and fuzzy entries when it continues.
- New strings and Weblate changes queue until the next start, by night window or by the day rule.
- `make i18n-translate` never revisits a filled entry, so the translator judges finished entries in a separate pass (`make test-oracle`) inside the window. The pass samples a fixed number of entries per language, so its cost grows with the number of languages, never with catalog size; it shares the model instance with the translation and is budgeted at about one hour of the window.
- An entry that fails the judgement is retranslated with the engine that produced it excluded (the gateway's `exclude` list on `/translate`). Every entry counts its attempts; after `agents.translator.max_attempts` failed attempts (default 3) it stays marked for a human and appears in the translator's report as a string no local engine can render. No entry is retried without a changed engine.
- The machine-translation marker in the catalogs records the engine that actually answered, not a fixed name, so a retry can exclude it.
- Engine-served languages run before chat-served ones, and chat lanes stay capped as `cli/build/i18n` sets them; the translator does not raise the cap.
- The full `test-integration` coverage of every language in both domains is not a gate the nightly window is expected to reach; its scope is the operator's decision.
- One pull request per language (`update/i18n-<language>-<date>`), carrying only that language's catalogs; algorithm changes go into their own pull requests, never mixed with catalog updates.
- The language set is what `domain_languages()` returns for each domain: every non-source language of `meta/languages.yml`. A pull request is opened only for a language whose catalogs changed; a language that has no catalog for a domain yet gets it created in its first pull request.
- A language pull request is opened only after its verification passed: every entry filled and not fuzzy, `msgfmt --check` clean, placeholders and protected spans identical to the source, glossary terms kept, and a sampled quality judgement by the chat judge (`utils/i18n/judge.py`, a chat model through `svc-ai-litellm`, three written-out levels, `temperature: 0`) at or above the language's last accepted level. A judge reply without a level aborts the verification instead of scoring.
- An algorithm change (router parameters such as fall-through order, failure threshold and settle rule; an engine's declared capabilities such as `services.libretranslate-engine.serves`; masking; damage predicate; glossary; client settings) is opened only with a benchmark: a fixed evaluation set per language built from human-reviewed Weblate strings, scored by the chat judge before and after; it must improve at least one language and lower none.
- The translator never reads or writes a per-language engine: `meta/languages.yml` holds only name, native name and direction, and which engine answers a language is the router's decision.
- Algorithm changes to `web-svc-translate`, `svc-ai-s1` and `utils/i18n` (the catalog marker included) are announced to the owner of the translation gateway before the pull request opens.
