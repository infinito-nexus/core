# Design Utilities 🎨

Color math and token derivation for the corporate design served by `web-svc-design`.

## Modules 📦

| Module | Purpose |
|---|---|
| [palette.py](palette.py) | Derives the `--design-*` tokens for light and dark mode from one base color in OKLCH, with WCAG 2.2 contrast checked on the rounded hex value. |

## Example Imports ✍️

```python
from utils.design.palette import build_palette, contrast
```
