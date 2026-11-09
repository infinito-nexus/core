# Design Utilities 🎨

Color math and token derivation for the corporate design served by `web-svc-design`.

## Modules 📦

| Module | Purpose |
|---|---|
| [palette.py](palette.py) | Derives the `--design-*` tokens for light and dark mode from one base color in OKLCH, with WCAG 2.2 contrast checked on the rounded hex value. |
| [film_theme.py](film_theme.py) | Maps the dark palette and the design font onto the theme tokens of films and release images, returns the logo path and fills an SVG template's theme placeholders (`python -m utils.design.film_theme`). |

## Example Imports ✍️

```python
from utils.design.palette import build_palette, contrast
```
