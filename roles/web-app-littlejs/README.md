# LittleJS

## Description

**LittleJS** is a self-hosted web application that bundles the LittleJS engine, its official examples, and a minimal Infinito.Nexus launcher UI.
It provides a simple, tile-based overview of demos and games, allowing you to quickly explore LittleJS examples directly in your browser.

## Overview

LittleJS Playground is designed as a lightweight HTML5 game sandbox for education, prototyping, and fun.
It exposes the original LittleJS `examples/` browser and adds a Bootstrap-based landing page that lists all examples as clickable tiles and offers quick links to popular games such as platformers and arcade-style demos.
The app runs as a single Docker container and requires no additional database or backend services.

## Features

- **Self-hosted LittleJS environment**: run LittleJS demos and games under your own domain.
- **Example browser integration**: direct access to the original LittleJS example browser.
- **Tile-based launcher UI**: dynamically renders a catalog from the `exampleList` definition.
- **Quick links for games**: navbar entries for selected games (e.g. platformer, pong, space shooter).
- **Bootstrap-styled interface**: clean, minimalistic, and responsive layout.
- **Docker-ready**: fully integrated into the Infinito.Nexus Docker stack.

## Further Resources

- Upstream engine & examples: [KilledByAPixel/LittleJS](https://github.com/KilledByAPixel/LittleJS)
- LittleJS README & docs: [GitHub – LittleJS](https://github.com/KilledByAPixel/LittleJS#readme)

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) pins `sso.enabled` and `logout.enabled` to `false`; the role serves the upstream LittleJS build from a static nginx image and ships no auth layer at all. There is nothing for the `biber` or `administrator` persona to log in to, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline reachability assertions run unconditionally.
