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

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
