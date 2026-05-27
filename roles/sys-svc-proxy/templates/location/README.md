# NGINX Location Templates

This directory contains Jinja2 templates for different NGINX `location` blocks, each designed to proxy and optimize different types of web traffic. These templates are used by the `sys-svc-proxy` role to modularize and standardize reverse proxy configuration across a wide variety of applications.

---

## Overview of Files

### `html.conf.j2`

- **Purpose:**  
  Handles "normal" web traffic such as HTML pages, API endpoints, and general HTTP(S) requests.
- **Features:**  
  - Proxies requests to the backend service.
  - Optionally integrates with OAuth2 proxy for authentication.
  - Sets all necessary proxy headers.
  - Applies a Content Security Policy header.
  - Activates buffering for advanced features such as Lua-based string replacements.
  - Supports WebSocket upgrades for hybrid APIs.

---

### `ws.conf.j2`

- **Purpose:**  
  Handles WebSocket connections, enabling real-time features such as live updates or chats.
- **Features:**  
  - Sets all headers required for WebSocket upgrades.
  - Disables proxy buffering (required for WebSockets).
  - Uses `tcp_nodelay` for low latency.
  - Proxies traffic to the backend WebSocket server.

---

### `media.conf.j2`

- **Purpose:**  
  Proxies and caches static media files (images, icons, etc.).
- **Features:**  
  - Matches image file extensions (jpg, png, gif, webp, ico, svg, etc.).
  - Enables browser-side and proxy-side caching for efficient delivery.
  - Adds cache control headers and exposes the upstream cache status.

---

## Usage

These templates are intended for inclusion in larger NGINX configuration files via Jinja2.  
They modularize your configuration by separating HTML, WebSocket, and media proxying, allowing for clear, reusable, and maintainable reverse proxy logic.

- Use `html.conf.j2` for standard application HTTP/S endpoints.
- Use `ws.conf.j2` for dedicated WebSocket endpoints.
- Use `media.conf.j2` for efficient handling of static media content.

---

## Best Practices

- Only enable WebSocket proxying (`ws.conf.j2`) for routes that actually require it, to avoid breaking buffering for standard HTTP.
- Activate media proxying (`media.conf.j2`) if your application benefits from image caching at the proxy layer.
- Keep templates modular for maintainability and scalability as your application grows.
