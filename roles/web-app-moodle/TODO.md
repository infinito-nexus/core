# TODO

- The TinyMCE editor keeps its own skin in dark mode: on `/user/edit.php` the gallery measured `#222f3e` (46487 px) and `#212529` in the editor toolbar, neither a design token. The toolbar and the editor content load their own stylesheets (TinyMCE skin, Boost `editor.scss` compiled without the raw SCSS setting), so the `theme_boost/scss` mapping does not reach them. Options, not measured: a Boost child theme that adds the mapping to its editor sheet, or a TinyMCE skin or content stylesheet setting of `editor_tiny`.
