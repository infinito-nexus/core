# File Server

## Description

The NGINX File Server role sets up a simple and secure static file server using [NGINX](https://NGINX.org/). It provides an easy way to serve files over HTTPS, including directory listing, `.well-known` support, and automatic SSL/TLS certificate integration via Let's Encrypt.

## Overview

Optimized for Archlinux, this role configures NGINX to act as a lightweight and efficient file server. It ensures that files are served securely, with optional directory browsing enabled, and proper MIME type handling for standard web clients.

## Features

- **Automatic SSL/TLS Certificate Management:** Integrates with Let's Encrypt for secure access.
- **Simple Configuration:** Minimal setup with clear, maintainable templates.
- **Directory Listings:** Enables browsing through served files with human-readable file sizes and timestamps.
- **Static Content Hosting:** Serve any type of static files (documents, software, media, etc.).
- **Well-Known Folder Support:** Allows serving validation files and other standardized resources easily.

## Further Resources

- [NGINX Official Website](https://NGINX.org/)
- [Let's Encrypt](https://letsencrypt.org/)
- [HTTPS (Wikipedia)](https://en.wikipedia.org/wiki/HTTPS)
