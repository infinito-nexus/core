# TODO

- Product name: the sidebar title, the `alt` text of the sign-in logo, the web app manifest (`name`, icons) and the launch screen logo still show Home Assistant; the frontend offers no setting for them, and the theme and the sign-in stylesheet do not reach them.
- Sign-in stylesheet: `templates/style.css.j2` repeats the `--wa-color-*` assignments Home Assistant derives on `html`, because the sign-in page takes no theme. Compare the list with the frontend when the image version moves.
