# Content Delivery Network

CDN helper role for building a consistent asset tree, URLs, and on-disk layout.

## Description

Provides compact filters and defaults to define CDN paths, turn them into public URLs, collect required directories, and prepare the filesystem (including a `latest` release link).

## Overview

Defines a per-role CDN structure under `roles/<application_id>/<version>` plus shared and vendor areas. Exposes ready-to-use variables (`cdn`, `cdn_dirs`, `cdn_urls`) and ensures directories exist. Optionally links the current release to `latest`.

## Features

* Jinja filters: `cdn_paths`, `cdn_urls`, `cdn_dirs`
* Variables: `CDN_ROOT`, `CDN_VERSION`, `CDN_BASE_URL`, `cdn`, `cdn_dirs`, `cdn_urls`
* Creates shared/vendor/release directories
* Maintains `roles/<id>/latest` symlink (when version ≠ `latest`)
* Plays nicely with `web-svc-cdn` without circular inclusion
