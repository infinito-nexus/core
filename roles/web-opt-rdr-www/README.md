# World Wide Web

## Description

Automates the creation of NGINX server blocks that redirect all `www.` subdomains to their non-www equivalents. Simple, idempotent, and SEO-friendly! 🚀

## Overview

This role will:

- **Discover** existing `*.conf` vhosts in your NGINX servers directory  
- **Filter** domains with or without your `DOMAIN_PRIMARY`  
- **Generate** redirect rules via the `web-opt-rdr-domains` role  
- **Optionally** include a wildcard redirect template (experimental) ⭐️  
- **Clean up** leftover configs when running in cleanup mode 🧹  

All tasks are guarded by “run once” facts and `CLEANUP` flags to avoid unintended re-runs or stale files.

## Purpose

Ensure that any request to `www.example.com` automatically and permanently redirects to `https://example.com`, improving user experience, SEO, and certificate management. 🎯

## Features

- **Auto-Discovery**: Scans your NGINX `servers` directory for `.conf` files. 🔍  
- **Dynamic Redirects**: Builds `source: "www.domain"` → `target: "domain"` mappings on the fly. 🔧  
- **Wildcard Redirect**: Includes a templated wildcard server block for `www.*` domains (toggleable). ✨  
- **Cleanup Mode**: Removes the wildcard config file when `CERTBOT_FLAVOR` is set to `dedicated` and `CLEANUP` is enabled. 🗑️
- **Cloudflare Edge Flavor**: With `DNS_PROVIDER: cloudflare` and the `edge` flavor, every mapping whose source and target are clearnet names becomes a Cloudflare redirect rule. Every other mapping, such as one with an onion end, gets its redirect from the origin through `web-opt-rdr-domains`: an onion name has no Cloudflare zone and is never sent to the Cloudflare API. ☁️
- **Debug Output**: Optional `DEBUG` gives detailed variable dumps for troubleshooting. 🐛  
