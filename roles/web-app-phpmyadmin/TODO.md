# TODO

- The home view of every deploy shows "The phpMyAdmin configuration storage is not completely configured, some extended features have been deactivated" (measured on variant 0, 2026-10-10): no `pmadb` is configured for server 1, so bookmarks, the designer, user preferences in the database and the relation features stay off. Options: point `$cfg['Servers'][1]['pmadb']` and the control user at the role database through `PMA_PMADB`/`PMA_CONTROLUSER` in `templates/env.j2` and let phpMyAdmin create its tables, or hide the notice with `$cfg['PmaNoRelation_DisableWarning']`.
