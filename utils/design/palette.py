"""Corporate design palette derived from a single base color in OKLCH.

Contrast targets are checked on the rounded 8-bit hex value, not on the float
color: rounding alone can drop a borderline token below its WCAG threshold.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

SCALE_STEPS: tuple[int, ...] = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
_SCALE_LIGHTNESS = (0.97, 0.94, 0.88, 0.80, 0.71, 0.62, 0.54, 0.46, 0.38, 0.30, 0.22)
_SCALE_CHROMA_SHAPE = (0.25, 0.4, 0.6, 0.8, 0.95, 1.0, 1.0, 0.95, 0.85, 0.75, 0.6)

CONTRAST_BODY_TEXT = 7.0
CONTRAST_TEXT = 4.5
CONTRAST_UI = 3.0

STATUS_HUES: dict[str, float] = {
    "success": 145.0,
    "warning": 75.0,
    "danger": 27.0,
    "info": 245.0,
}

_SURFACE_LIGHTNESS = {
    "light": (0.975, 0.995, 0.935),
    "dark": (0.17, 0.215, 0.26),
}
_TEXT_LIGHTNESS = {"light": 0.23, "dark": 0.94}
_TEXT_MUTED_LIGHTNESS = {"light": 0.45, "dark": 0.72}
_BORDER_LIGHTNESS = {"light": 0.88, "dark": 0.32}
_BORDER_STRONG_LIGHTNESS = {"light": 0.62, "dark": 0.55}
_STATUS_LIGHTNESS = {"light": 0.55, "dark": 0.75}
_SURFACE_STATE_LIGHTNESS = {
    "light": {"hover": 0.905, "active": 0.875},
    "dark": {"hover": 0.30, "active": 0.34},
}
_FRAME_LIGHTNESS = {"light": 0.38, "dark": 0.30}
_FILL_STATE_SHIFT = {"hover": 0.04, "active": 0.08}
_STATUS_TINT_SHARE = {"subtle": 0.12, "border": 0.40}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_LIGHTNESS_STEP = 0.005


def parse_hex(value: str) -> tuple[float, float, float]:
    """Parse ``#rrggbb`` or ``#rgb`` into sRGB channels in ``[0, 1]``.

    Args:
        value: Hex color string, with or without the leading ``#``.

    Returns:
        The red, green and blue channels.

    Raises:
        ValueError: When ``value`` is not a 3 or 6 digit hex color.
    """
    match = _HEX_RE.match(str(value).strip())
    if not match:
        raise ValueError(
            f"design.colors.base must be a hex color such as '#001f3f', got {value!r}"
        )
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return tuple(int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _from_linear(channel: float) -> float:
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * channel ** (1 / 2.4) - 0.055


def _cbrt(value: float) -> float:
    return math.copysign(abs(value) ** (1 / 3), value)


def _rgb_to_oklch(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in rgb)
    l_ = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.hypot(a, bb)
    hue = math.degrees(math.atan2(bb, a)) % 360
    return lightness, chroma, hue


def _oklch_to_linear(
    lightness: float, chroma: float, hue: float
) -> tuple[float, float, float]:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _in_gamut(linear: tuple[float, float, float]) -> bool:
    return all(-1e-6 <= c <= 1 + 1e-6 for c in linear)


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """Convert OKLCH to hex, reducing chroma until the color fits sRGB.

    Args:
        lightness: OKLCH lightness in ``[0, 1]``.
        chroma: Requested OKLCH chroma.
        hue: OKLCH hue in degrees.

    Returns:
        The ``#rrggbb`` hex string.
    """
    lightness = min(max(lightness, 0.0), 1.0)
    if not _in_gamut(_oklch_to_linear(lightness, chroma, hue)):
        low, high = 0.0, chroma
        for _ in range(24):
            mid = (low + high) / 2
            if _in_gamut(_oklch_to_linear(lightness, mid, hue)):
                low = mid
            else:
                high = mid
        chroma = low
    channels = (
        _from_linear(min(max(c, 0.0), 1.0))
        for c in _oklch_to_linear(lightness, chroma, hue)
    )
    return "#" + "".join(f"{round(c * 255):02x}" for c in channels)


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.2 relative luminance of a hex color.

    Args:
        hex_color: ``#rrggbb`` or ``#rgb``.

    Returns:
        The luminance in ``[0, 1]``.
    """
    r, g, b = (_to_linear(c) for c in parse_hex(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG 2.2 contrast ratio between two hex colors.

    Args:
        first: Hex color.
        second: Hex color.

    Returns:
        The ratio in ``[1, 21]``.
    """
    high, low = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (high + 0.05) / (low + 0.05)


def _mix(color: str, surface: str, share: float) -> str:
    channels = zip(parse_hex(color), parse_hex(surface), strict=True)
    return "#" + "".join(
        f"{round((share * c + (1 - share) * s) * 255):02x}" for c, s in channels
    )


def _ensure_contrast(
    lightness: float,
    chroma: float,
    hue: float,
    against: list[str],
    target: float,
    step: float,
    tint: Callable[[str], str] | None = None,
) -> str:
    while 0.0 <= lightness <= 1.0:
        candidate = oklch_to_hex(lightness, chroma, hue)
        backgrounds = [*against, tint(candidate)] if tint else against
        if min(contrast(candidate, surface) for surface in backgrounds) >= target:
            return candidate
        lightness += step
    raise ValueError(f"no lightness reaches contrast {target} for hue {hue:.1f}")


def _best_on_color(background: str) -> str:
    return max(("#ffffff", "#000000"), key=lambda fg: contrast(fg, background))


def _fill_tokens(name: str, fill: str) -> dict[str, str]:
    on_color = _best_on_color(fill)
    lightness, chroma, hue = _rgb_to_oklch(parse_hex(fill))
    direction = 1 if on_color == "#000000" else -1
    tokens = {f"--design-{name}": fill, f"--design-on-{name}": on_color}
    for state, shift in _FILL_STATE_SHIFT.items():
        tokens[f"--design-{name}-{state}"] = oklch_to_hex(
            lightness + direction * shift, chroma, hue
        )
    return tokens


def _rgb_triplet(hex_color: str) -> str:
    return ", ".join(str(round(c * 255)) for c in parse_hex(hex_color))


def _with_rgb(tokens: dict[str, str]) -> dict[str, str]:
    result = dict(tokens)
    for name, value in tokens.items():
        result[f"{name}-rgb"] = _rgb_triplet(value)
    return result


def _scale(mode: str, prefix: str, chroma: float, hue: float) -> dict[str, str]:
    lightness = _SCALE_LIGHTNESS if mode == "light" else _SCALE_LIGHTNESS[::-1]
    shape = _SCALE_CHROMA_SHAPE if mode == "light" else _SCALE_CHROMA_SHAPE[::-1]
    return {
        f"--design-{prefix}-{step}": oklch_to_hex(level, chroma * factor, hue)
        for step, level, factor in zip(SCALE_STEPS, lightness, shape, strict=True)
    }


def _mode_tokens(
    mode: str, base: str, base_lch: tuple[float, float, float]
) -> dict[str, str]:
    base_l, base_c, hue = base_lch
    neutral_c = min(base_c * 0.12, 0.018)
    status_c = min(max(base_c, 0.11), 0.17)
    away = -_LIGHTNESS_STEP if mode == "light" else _LIGHTNESS_STEP
    surfaces = [
        oklch_to_hex(lightness, neutral_c, hue)
        for lightness in _SURFACE_LIGHTNESS[mode]
    ]
    content_surfaces = surfaces[:2]
    state_surfaces = {
        state: oklch_to_hex(lightness, neutral_c, hue)
        for state, lightness in _SURFACE_STATE_LIGHTNESS[mode].items()
    }
    text_surfaces = [*surfaces, *state_surfaces.values()]

    if (
        mode == "light"
        and min(contrast(base, s) for s in content_surfaces) >= CONTRAST_UI
    ):
        primary = base
    else:
        start = base_l if mode == "light" else max(base_l, 0.6)
        primary = _ensure_contrast(
            start, base_c, hue, content_surfaces, CONTRAST_UI, away
        )

    tokens = {
        **_scale(mode, "primary", base_c, hue),
        **_scale(mode, "neutral", neutral_c, hue),
        "--design-surface-1": surfaces[0],
        "--design-surface-2": surfaces[1],
        "--design-surface-3": surfaces[2],
        "--design-surface-hover": state_surfaces["hover"],
        "--design-surface-active": state_surfaces["active"],
        "--design-text": _ensure_contrast(
            _TEXT_LIGHTNESS[mode],
            neutral_c,
            hue,
            text_surfaces,
            CONTRAST_BODY_TEXT,
            away,
        ),
        "--design-text-muted": _ensure_contrast(
            _TEXT_MUTED_LIGHTNESS[mode],
            neutral_c,
            hue,
            text_surfaces,
            CONTRAST_TEXT,
            away,
        ),
        "--design-border": oklch_to_hex(_BORDER_LIGHTNESS[mode], neutral_c, hue),
        "--design-border-strong": _ensure_contrast(
            _BORDER_STRONG_LIGHTNESS[mode],
            neutral_c,
            hue,
            content_surfaces,
            CONTRAST_UI,
            away,
        ),
        **_fill_tokens("primary", primary),
        **_fill_tokens(
            "frame",
            oklch_to_hex(
                min(base_l, _FRAME_LIGHTNESS[mode])
                if mode == "light"
                else _FRAME_LIGHTNESS[mode],
                base_c,
                hue,
            ),
        ),
        "--design-link": _ensure_contrast(
            min(base_l, 0.55) if mode == "light" else max(base_l, 0.7),
            base_c,
            hue,
            text_surfaces,
            CONTRAST_TEXT,
            away,
        ),
    }
    for name, status_hue in STATUS_HUES.items():
        color = _ensure_contrast(
            _STATUS_LIGHTNESS[mode],
            status_c,
            status_hue,
            text_surfaces,
            CONTRAST_TEXT,
            away,
            tint=lambda fill: _mix(fill, surfaces[1], _STATUS_TINT_SHARE["subtle"]),
        )
        tokens.update(_fill_tokens(name, color))
        for tint, share in _STATUS_TINT_SHARE.items():
            tokens[f"--design-{name}-{tint}"] = _mix(color, surfaces[1], share)
    return tokens


def build_palette(base: str) -> dict[str, dict[str, str]]:
    """Derive the full corporate design palette from one base color.

    Args:
        base: Hex base color (``design.colors.base``).

    Returns:
        ``{"light": {...}, "dark": {...}}``, each keyed by CSS custom property
        name; every color also carries a ``<name>-rgb`` entry with its
        ``r, g, b`` triplet. Scale step 50 sits next to the surface and 950
        next to the text in both modes.

    Raises:
        ValueError: When ``base`` is not a hex color.
    """
    rgb = parse_hex(base)
    base_hex = "#" + "".join(f"{round(c * 255):02x}" for c in rgb)
    base_lch = _rgb_to_oklch(rgb)
    return {
        "light": _with_rgb(_mode_tokens("light", base_hex, base_lch)),
        "dark": _with_rgb(_mode_tokens("dark", base_hex, base_lch)),
    }
