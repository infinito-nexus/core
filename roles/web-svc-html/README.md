# NGINX HTML Server

## Description

This role configures an [NGINX](https://NGINX.org/) server to host a static HTML homepage securely over HTTPS. It automates domain configuration, SSL/TLS certificate retrieval using [Let's Encrypt](https://letsencrypt.org/), and ensures your site is ready for production with minimal setup.

## Overview

Optimized for Archlinux environments, this role provides a lightweight, reliable solution for serving static websites. It automatically configures NGINX to serve files from a predefined directory, sets up secure HTTPS connections, and includes support for `.well-known` paths required by ACME challenges.

### Key Features

- **Static Site Hosting:** Serves HTML, CSS, JavaScript, and other static files.
- **Let's Encrypt Integration:** Automatically requests and installs SSL/TLS certificates.
- **Simple Root Configuration:** Defines a clean webroot with `index.html` support.
- **Secure by Default:** Includes modern SSL headers and best practices via NGINX.
- **.well-known Support:** Ensures full ACME challenge compatibility.

## Purpose

The NGINX Static HTML Server role provides a simple and efficient method to publish static websites with HTTPS, perfect for personal homepages, landing pages, or small projects.

## Features

- **Automatic HTTPS Certificates:** Handles secure certificate issuance via Let's Encrypt.
- **Minimal NGINX Setup:** Clean and optimized default configurations.
- **Highly Portable:** Works out-of-the-box with minimal variables.
- **Local Time Support:** Properly displays directory listing timestamps when needed.

## Learn More

- [NGINX Official Website](https://NGINX.org/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Static Web Page (Wikipedia)](https://en.wikipedia.org/wiki/Static_web_page)
- [HTTPS (Wikipedia)](https://en.wikipedia.org/wiki/HTTPS)

## ‍ Author Information

Created in 2023 by [Kevin Veen-Birkenbach](https://www.veen.world/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
