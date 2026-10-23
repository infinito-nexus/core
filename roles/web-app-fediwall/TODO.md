# Todos

- Implement multi-wall runtime upload behind OIDC (archived req 016).
- The wall list page (more than one wall) links `./favicon.png` at the site root in `templates/index.html.j2`, and `https://<domain>/favicon.png` answers 404 because `tasks/01_manager_ops.yml` stages the icons per wall slug only. Options: stage the three icons at the root too, or link the icon of the first wall.
