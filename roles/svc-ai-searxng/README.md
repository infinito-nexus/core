# Searxng

## Description

[SearXNG](https://docs.searxng.org/) is a metasearch engine. It forwards a query to other search engines and returns the merged result without an account and without a tracking profile.

## Overview

The role renders `settings.yml` from the deployment's own secret key and mounts it read-only. `formats` carries `json` next to `html`, because a machine consumer gets HTTP 403 on the JSON endpoint otherwise, and the rate limiter is off since the only clients are platform services on the container network.

A consumer reaches it as `http://searxng:8080/search?q=<query>` once it declares `searxng` in its own `meta/services.yml` with `enabled` and `shared` set. `web-app-openwebui` ships that flag and sends `WEB_SEARCH_ENGINE=searxng` with it.

## Features

- **JSON enabled:** the settings add the `json` output format, which upstream ships disabled and which every API client needs.
- **Internal only:** no published port, no proxy entry; the limiter is off because the clients are platform services.
- **Named state:** the configuration and cache directories the image declares as volumes are pinned to named volumes, so no anonymous volume is left behind.
