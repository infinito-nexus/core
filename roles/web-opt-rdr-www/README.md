# NGINX WWW Redirect

## Description

Automates the creation of NGINX server blocks that redirect all `www.` subdomains to their non-www equivalents. Simple, idempotent, and SEO-friendly! 🚀

## Overview

This role will:

- **Discover** existing `*.conf` vhosts in your NGINX servers directory  
- **Filter** domains with or without your `DOMAIN_PRIMARY`  
- **Generate** redirect rules via the `web-opt-rdr-domains` role  
- **Optionally** include a wildcard redirect template (experimental) ⭐️  
- **Clean up** leftover configs when running in cleanup mode 🧹  

All tasks are guarded by “run once” facts and `MODE_CLEANUP` flags to avoid unintended re-runs or stale files.

## Purpose

Ensure that any request to `www.example.com` automatically and permanently redirects to `https://example.com`, improving user experience, SEO, and certificate management. 🎯

## Features

- **Auto-Discovery**: Scans your NGINX `servers` directory for `.conf` files. 🔍  
- **Dynamic Redirects**: Builds `source: "www.domain"` → `target: "domain"` mappings on the fly. 🔧  
- **Wildcard Redirect**: Includes a templated wildcard server block for `www.*` domains (toggleable). ✨  
- **Cleanup Mode**: Removes the wildcard config file when `CERTBOT_FLAVOR` is set to `dedicated` and `MODE_CLEANUP` is enabled. 🗑️
- **Debug Output**: Optional `MODE_DEBUG` gives detailed variable dumps for troubleshooting. 🐛  

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
