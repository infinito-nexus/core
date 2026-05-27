# Locales

This Ansible role manages the system locale configuration by deploying `locale.gen` and `locale.conf`, then generating the requested locales.

## Description

- Copies your `locale.gen` template to `/etc/locale.gen`  
- Copies your `locale.conf` template to `/etc/locale.conf`  
- Runs `locale-gen` to generate and activate configured locales  

## Overview

1. **Template deployment**  
   - `locale.gen`: uncomment or specify the locales you need  
   - `locale.conf`: sets `LANG` and `LANGUAGE` environment variables  
2. **Locale generation**  
   - Executes the `locale-gen` command (requires privilege escalation)  
3. **Idempotency**  
   - Templates are only reapplied if changed  
   - `locale-gen` only re-runs when the template changes

## Features

- Full control over uncommented locales in `locale.gen`
- Simple override via templates in your role directory
- Works on any system supporting `locale-gen`

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
