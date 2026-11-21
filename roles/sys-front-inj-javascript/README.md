# Global JavaScript Injector for NGINX

## Description

This Ansible role injects a custom JavaScript snippet into all HTML responses served by NGINX. It leverages NGINX’s `sub_filter` to seamlessly insert your application-specific script just before the closing `</head>` tag, ensuring that your code runs on every page load, which is useful for global feature flags, analytics, or UI enhancements.

## Overview

This role injects a custom JavaScript snippet into Nginx-served HTML responses via sub_filter.

## Features

- **One-line Script Injection**  
  Collapses your JavaScript into a single line and injects it via `sub_filter` for minimal footprint and maximal compatibility.

- **Easy CSP Integration**  
  Automatically computes and appends a CSP hash entry for your script, so you can lock down Content Security Policy without lifting a finger.

- **Conditional Activation**  
  Activates only when you enable the `javascript` feature for a given application, keeping your server blocks clean and performant.

- **SSO Profile Lock**  
  `templates/profile_lock.js.j2` renders every input matched by the selectors of the role's `sso.<claim>` fields in `meta/forms.yml` read-only and shows the `locked` text of `files/profile_lock_i18n.yml` in the page language as its hover title. Every control but a `textarea` or a text-like input ignores `readOnly`, so the renderer disables it, a button included, and adds a hidden input per value the control would submit (the checked radio or checkbox, every selected option, a color or range value; none for a button or a file input), so a settings page that saves every option it renders still receives the managed value; an unlock removes those inputs again. It locks every other `enforced` field of the role's `meta/forms.yml` the same way, with the `managed` text and the field's inventory path, lists them in one banner per page and unlocks every control of one field after a double-click and a confirmation; `lookup('field_locks', application_id)` hands it both. `templates/profile_lock_catalogue.json.j2` cuts the catalogue to the role's `services.sso.profile.languages` and keeps every language for a role that declares none; the Playwright env of a role renders the same file. A role includes the renderer from its own `templates/javascript.js.j2`; see [javascript.js.md](../../docs/contributing/artefact/files/role/javascript.js.md#sso-profile-lock-).

- **Debug Mode**  
  Supports a `DEBUG` flag that appends optional `console.log` statements for easier troubleshooting in staging or development.
