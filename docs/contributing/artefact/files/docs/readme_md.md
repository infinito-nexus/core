# Docs README 📄

This page covers `README.md` files stored inside `docs/` directories.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../documentation.md).

## Purpose 🎯

A docs `README.md` MUST explain what kind of documentation lives in that directory and what scope that documentation covers.
It MUST help readers understand the subject area and boundary of the folder without replacing the documentation pages themselves.

## Scope 📋

- A docs `README.md` MUST stay short and scope-focused.
- A docs `README.md` MUST describe the audience, subject area, or boundary of the documentation in that directory when that context helps readers.
- A docs `README.md` MUST NOT act as a manual index, table of contents, or page inventory.
- A docs `README.md` MUST NOT list the `.md` or `.rst` files in the directory.
- Page indexing for documentation directories MUST be handled by `index.rst`, not by `README.md`.

## Navigation 🔗

- Documentation pages inside the directory MUST cross-link to each other directly when readers need contextual navigation.
- A docs `README.md` MUST NOT duplicate navigation that Sphinx already provides.
