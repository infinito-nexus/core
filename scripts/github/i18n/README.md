# GitHub i18n Helpers 🌐

This directory contains the shell helpers that [entry-pr-translate.yml](../../../.github/workflows/entry-pr-translate.yml) calls: resolving the languages LibreTranslate supports into the job matrix, merging the source strings of the `core` and `docs` domains into `locale/`, and machine-translating one language per runner.

| Helper | Purpose |
|---|---|
| [install_python.sh](install_python.sh) | Installs the package with the `dev` extra, which carries Sphinx for the `docs` extraction. |
| [languages.sh](languages.sh) | Writes the machine-translatable ISO 639-1 codes to `GITHUB_OUTPUT` as a JSON array. |
| [extract.sh](extract.sh) | Merges the source strings of both domains into every catalog under `locale/`. |
| [translate.sh](translate.sh) | Translates the empty and fuzzy entries of one language in both domains. |
