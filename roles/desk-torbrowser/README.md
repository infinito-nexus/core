# Torbrowser

## Description

This Ansible role installs and configures the Tor service and the Tor Browser Launcher, providing a privacy-focused web browsing environment on Pacman-based Linux distributions.

## Overview

The `desk-torbrowser` role uses the `community.general.pacman` module to:

1. Install **tor** (the core Tor network service)  
2. Install **torbrowser-launcher** (the launcher for Tor Browser)  

## Features

* Idempotent installation of Tor and Tor Browser Launcher  
* Ensures the Tor service is available for anonymous network traffic  
* Simplifies first-time setup of Tor Browser  

## Further Resources

* [Tor Project documentation](https://www.torproject.org/)
* [Infinito.Nexus GitHub repository](https://s.infinito.nexus/code)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
