# To-dos

- The preview shows its background box without a code until the data changes: in the bottom sheet trigger below 768 px and right after "Add frame" is switched on. Measured on `v0.26.3` with and without the injected design. Cause: upstream, the remounted preview component draws only on a property change. Options: an upstream fix, or a newer image.
- The `og:` images stay upstream. They are compiled into the image; the injected stylesheet and script do not reach them. Options: build the image in the role, or mount replacements over `/app/dist`.
