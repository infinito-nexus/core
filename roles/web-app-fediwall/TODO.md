# Todos

- Implement multi-wall runtime upload behind OIDC (archived req 016).
- The wall list page (more than one wall) links `./favicon.png` at the site root in `templates/index.html.j2`, and `https://<domain>/favicon.png` answers 404 because `tasks/01_manager_ops.yml` stages the icons per wall slug only. Options: stage the three icons at the root too, or link the icon of the first wall.
- The wall list page without the `design` service shows a hovered wall link in `#1a73e8` on `#f0f4ff`, contrast 4.10:1 where text needs 4.5:1. Cause: the color literals in `templates/index.html.j2`. Options: darken the link literal, or lighten the hover background.
