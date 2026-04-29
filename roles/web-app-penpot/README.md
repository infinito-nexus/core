# Penpot

## Description

[Penpot](https://penpot.app/) is an open-source design and prototyping platform for cross-domain teams. It offers a collaborative environment for designers and developers to create, prototype, and share design projects with real-time collaboration features and developer-friendly export capabilities.

## Overview

This role provides a fully automated deployment of Penpot using Docker Compose on the Infinito.Nexus platform. It manages the entire lifecycle of the deployment, from container orchestration to OIDC/LDAP integration, ensuring a production-ready design platform that integrates seamlessly with the Infinito.Nexus infrastructure.

The setup includes support for real-time collaboration via WebSockets, asset storage management, email notifications, and multiple authentication methods. The role is modular and integrates with Infinito.Nexus shared services including reverse proxy configuration, domain management, database management, and backup systems.

## Purpose

To provide teams with a sovereign, self-hosted design and prototyping platform that enables:
- Design creation and editing with a Figma-like interface
- Real-time team collaboration with comments and live cursors
- Asset management with shared libraries and components
- Version history and design versioning
- Export capabilities (SVG, PDF, code)
- Developer handoff with CSS and code export

## Features

- **Open-Source Design Tool:** Create professional designs with a modern, web-based interface
- **Real-Time Collaboration:** Work simultaneously with team members on design projects
- **Asset Management:** Organize and share design components, libraries, and assets
- **Version Control:** Track design changes with built-in version history
- **Developer Handoff:** Export designs as SVG, PDF, or code snippets (CSS, HTML)
- **OIDC Integration:** Seamless authentication via Keycloak with SSO support
- **LDAP Support:** Alternative authentication via OpenLDAP directory services
- **Email Notifications:** SMTP integration for user invitations and notifications
- **WebSocket Support:** Real-time updates and live collaboration features
- **Redis Caching:** Performance optimization for WebSocket coordination
- **Automated Backups:** Integration with Infinito.Nexus backup roles for data protection
- **CSP Configuration:** Proper Content Security Policy setup via nginx reverse proxy

## Architecture

The Penpot deployment consists of four main services:

1. **Frontend (Nginx):** Serves the web UI and static assets
2. **Backend (Clojure/JVM):** Handles API requests, authentication, and business logic
3. **Exporter:** Renders design exports (SVG, PDF) 
4. **Redis:** Manages WebSocket notifications and real-time coordination
5. **PostgreSQL:** Stores design files, user data, and application state (managed by shared database role)

## Authentication

### OIDC (Recommended)

The role automatically configures OpenID Connect authentication using the Infinito.Nexus Keycloak instance. Users can log in with their centralized Keycloak accounts, enabling single sign-on across all platform applications.

Key OIDC environment variables:
- \`PENPOT_OIDC_CLIENT_ID\`
- \`PENPOT_OIDC_CLIENT_SECRET\`
- \`PENPOT_OIDC_BASE_URI\`
- Explicit URIs (\`PENPOT_OIDC_AUTH_URI\`, \`PENPOT_OIDC_TOKEN_URI\`, \`PENPOT_OIDC_USER_URI\`) configured to avoid discovery issues

### LDAP

Optional LDAP authentication via OpenLDAP is available when \`compose.services.ldap.enabled\` is set to \`true\` in the configuration.

## Storage

Penpot stores data in multiple locations:

- **Database:** PostgreSQL stores design files, user accounts, and metadata
- **Assets:** User-uploaded images, fonts, and design assets in Docker volume
- **Backups:** Automated via Infinito.Nexus backup roles for both database and asset volumes

Future: S3-compatible object storage can be configured for scalable asset storage.

## Developer Notes

### Java Trust Store

Per repository memory notes, Penpot backend requires a writable Java truststore for OIDC HTTPS connections. The compose configuration sets:
\`\`\`
JAVA_OPTS=-Djavax.net.ssl.trustStore=/tmp/java-cacerts -Djavax.net.ssl.trustStorePassword=changeit
\`\`\`

### WebSocket Configuration

The reverse proxy must properly forward WebSocket connections for real-time collaboration features. This is handled automatically by the Infinito.Nexus nginx CSP configuration.

### CSP Requirements

Penpot requires \`unsafe-inline\` for script-src-elem and style-src-attr due to its dynamic UI rendering. This is configured in \`config/main.yml\` under \`server.csp.flags\`.

## Configuration

Key configuration options in \`config/main.yml\`:

- **OIDC/LDAP:** Enable/disable authentication providers
- **Email:** Configure SMTP for user notifications
- **Resource Limits:** Adjust CPU, memory, and PID limits per service
- **Domains:** Set canonical domain (default: \`design.{{ DOMAIN_PRIMARY }}\`)

## Further Resources

- [Penpot Official Website](https://penpot.app/)
- [Penpot Documentation](https://help.penpot.app/)
- [Penpot GitHub Repository](https://github.com/penpot/penpot)
- [Penpot Docker Setup](https://help.penpot.app/technical-guide/getting-started/docker/)

## Credits

Developed and maintained by **Evangelos Tsakoudis**.  
Learn more at [www.evangelostsak.com](https://evangelostsak.com)

Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code)  
License: [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license)
