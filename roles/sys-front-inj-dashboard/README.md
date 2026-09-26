
# iFrame Notifier for NGINX

## Description

This Ansible role injects a small JavaScript snippet into your HTML responses that enables parent pages to get notified whenever the iframe’s location changes and forces external links to open in a new tab.

---

## Overview

This role injects a JS snippet into HTML to notify parent windows of iframe location changes and force external links to new tabs.

## Features

- **Location Change Notification**  
  Uses `postMessage` to inform the parent window of any URL changes inside the iframe (including pushState/popState events) for seamless SPA support.

- **External Link Handling**  
  Automatically sets `target="_blank"` and `rel="noopener"` on links pointing outside your primary domain to improve security and user experience.

- **Easy CSP Integration**  
  Calculates a CSP hash for the injected script so you can safely allow it via your Content Security Policy.
