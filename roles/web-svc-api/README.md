# API

## Description

The Infinito.Nexus API is a public, read-only REST service built with [FastAPI](https://fastapi.tiangolo.com/). It answers every question an app built on Infinito.Nexus asks about the platform: which roles exist, what their metadata says, how they are categorised, which bundles combine them, what the history of the repository and its forks looks like, and how all of that reads in each of the 184 ISO 639-1 languages.

## Overview

This role builds the API image from `files/Dockerfile`, bakes a snapshot of the deployed working tree into it and serves it at `api.<domain>`. The container keeps one bare git repository with the branches and tags of core, of every public fork (discovered through the GitHub forks endpoint) and the snapshot as the ref `deployed`, and fetches on a fixed interval. Every data endpoint takes a `ref`: `deployed`, a commit SHA, a branch or tag of core, or `<owner>:<branch or tag>` of a fork. Translations come from the `core` gettext catalogs under `locale/`, which `make i18n-extract` and `make i18n-translate` maintain.

The API has no authentication tier: it serves public repository data only, so SSO and logout are disabled and the Playwright persona scenarios are declared blocked for `biber` and `administrator`.

## Features

- **Every ref:** Role data, categories, bundles, files and TODO markers for the deployed working tree, any branch, tag or commit of core, and every branch or tag of its forks.
- **Translated data:** `lang` and `Accept-Language` translate role descriptions and category texts; `/v1/catalogs/core/<code>` returns a whole catalog as JSON and `/v1/languages` reports how complete each language is.
- **No clone needed:** `/v1/tree` and `/v1/file` read any path of a ref, `/v1/log` walks its history.
- **Safe with untrusted forks:** Trees are read as data only (safe YAML, Babel catalogs); refs and paths are validated before git sees them.
- **Cache friendly:** Responses for a commit SHA are immutable; every response carries `Access-Control-Allow-Origin: *`.

## Further Resources

- [FastAPI](https://fastapi.tiangolo.com/)
