# NGINX vHost Templates: Basic vs. WebSocket (ws_generic)

This directory provides two NGINX server templates for reverse proxying Dockerized applications behind NGINX:  

- `basic.conf.j2`
- `ws_generic.conf.j2`

---

## When to Use Which Template?

### 1. `basic.conf.j2`

**Use this template for standard HTTP/S applications.**  
It is optimized for typical web applications (e.g., static sites, PHP, Node.js, Django, etc.) that do **not** require persistent, bidirectional WebSocket connections.

- **Features:**
  - HTTP/2 support, TLS/SSL integration
  - Reverse proxy with buffering enabled (`proxy_buffering on`)
  - Allows advanced content filtering (e.g., via Lua body/headers)
  - Suitable for most REST APIs, web frontends, and admin panels

- **Pros:**
  - Enables HTML/body manipulation (for injecting snippets, analytics, CSP, etc.)
  - Optimized for efficient caching and GZIP compression
  - Good default for "normal" web traffic

- **Cons:**
  - **Not** suitable for WebSocket endpoints (buffering can break WS)
  - Slightly more latency for streaming data due to buffering

---

### 2. `ws_generic.conf.j2`

**Use this template for applications requiring WebSocket support.**  
Designed for services (e.g., chat servers, real-time dashboards) needing fast, persistent connections using the WebSocket protocol.

- **Features:**
  - WebSocket-aware: `proxy_buffering off`, special upgrade headers
  - Supports standard HTTP/S traffic alongside WebSockets
  - Proper handling of connection upgrades and protocol switching

- **Pros:**
  - Required for all WebSocket endpoints
  - Allows instant, low-latency bidirectional traffic
  - Prevents data loss or connection drops due to proxy buffering

- **Cons:**
  - Disables body/content filtering and response manipulation
  - No buffering means less effective for caching/optimization
  - Not suitable for scenarios requiring Lua/JS content injection

---

## Summary Table

| Use Case                 | Template            | Buffering | WebSocket? | Can Filter Content? |
|--------------------------|---------------------|-----------|------------|--------------------|
| Static/Classic Website   | `basic.conf.j2`     | On        | No         | Yes                |
| REST API                 | `basic.conf.j2`     | On        | No         | Yes                |
| Real-Time Chat/App       | `ws_generic.conf.j2`| Off       | Yes        | No                 |
| Dashboard w/Live Data    | `ws_generic.conf.j2`| Off       | Yes        | No                 |
| Needs HTML Injection     | `basic.conf.j2`     | On        | No         | Yes                |

---

## Good to Know

- **Never enable buffering for true WebSocket connections!**  
  Use `proxy_buffering off;` (as in `ws_generic.conf.j2`) or connections may fail.
- For most classic web applications, use the **basic template**.
- For apps where you want to inject or modify HTML (e.g., analytics scripts), **only the basic template** supports this.

---

## Author & Project

By [Kevin Veen-Birkenbach](https://www.veen.world)  
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code)  
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license)
