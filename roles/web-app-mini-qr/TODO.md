# To-dos

- Remove clarity.ms
- The preview shows its background box without a code until the data changes: in the bottom sheet trigger below 768 px and right after "Add frame" is switched on. Measured on `v0.26.3` with and without the injected design. Cause: upstream, the remounted preview component draws only on a property change. Options: an upstream fix, or a newer image.
- The PWA manifest keeps `name: MiniQR` and `theme_color: #ffffff`, and the `og:` images stay upstream. They are compiled into the image; the injected stylesheet and script do not reach them. Options: build the image in the role, or mount replacements over `/app/dist`.
- The camera view of the scanner keeps upstream colors (`.scanner-container`, `.spinner`, the scoped `.button`, the overlay buttons with `bg-white/80`). It opens only with a camera, which the test browser lacks. Options: a fake media device in the shared Playwright configuration, then a mapping in `templates/style.css.j2`.
