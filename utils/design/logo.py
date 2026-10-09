"""Logo lockups for the corporate design, rendered as SVG and PNG plus a favicon."""

from __future__ import annotations

import base64
import io
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

LAYOUT_LOGO = "logo"
LAYOUT_TITLE = "title"
LAYOUT_LOGO_TITLE = "logo_title"
LAYOUT_LOGO_TITLE_DOMAIN = "logo_title_domain"
LAYOUT_LOGO_STACKED = "logo_stacked"

FAVICON_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64))
_SQUARE_MAX_ASPECT = 1.5
_INLINE_DOMAIN_MIN_ASPECT = 6.0
_STACKED_MIN_HEIGHT = 96
_SVG_RASTER_MAX = 512


def choose_layout(width: int, height: int, text_only: bool, has_title: bool) -> str:
    """Pick the lockup for a slot from its format.

    Args:
        width: Slot width in pixels.
        height: Slot height in pixels.
        text_only: Slot accepts text only.
        has_title: A title is available.

    Returns:
        One of the ``LAYOUT_*`` constants.
    """
    aspect = width / height
    if text_only:
        return LAYOUT_TITLE
    if not has_title or aspect < _SQUARE_MAX_ASPECT:
        return LAYOUT_LOGO
    if height >= _STACKED_MIN_HEIGHT:
        return LAYOUT_LOGO_STACKED
    if aspect >= _INLINE_DOMAIN_MIN_ASPECT:
        return LAYOUT_LOGO_TITLE_DOMAIN
    return LAYOUT_LOGO_TITLE


def _trimmed_logo(path: str) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").getbbox()
    return image.crop(box) if box else image


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(6, size))


def _fit_font(text: str, max_width: int, max_size: int) -> ImageFont.FreeTypeFont:
    size = max_size
    while size > 6 and _font(size).getlength(text) > max_width:
        size -= 1
    return _font(size)


def _lines(layout: str, title: str, domain: str) -> list[tuple[str, float]]:
    if layout == LAYOUT_LOGO_STACKED:
        return [(title, 0.42), (domain, 0.22)]
    if layout == LAYOUT_LOGO_TITLE_DOMAIN:
        return [(f"{title} · {domain}", 0.5)]
    if layout in (LAYOUT_LOGO_TITLE, LAYOUT_TITLE):
        return [(title, 0.55)]
    return []


def _compose(
    logo_path: str | None, title: str, domain: str, width: int, height: int, layout: str
) -> tuple[
    Image.Image | None,
    tuple[int, int],
    list[tuple[str, ImageFont.FreeTypeFont, int, int]],
]:
    pad = max(1, round(height * 0.1))
    inner_w, inner_h = width - 2 * pad, height - 2 * pad
    logo_img, logo_xy, text_x = None, (0, 0), pad
    if layout != LAYOUT_TITLE and logo_path:
        box_w = inner_w if layout == LAYOUT_LOGO else inner_h
        logo_img = _fit(_trimmed_logo(logo_path), box_w, inner_h)
        if layout == LAYOUT_LOGO:
            logo_xy = ((width - logo_img.width) // 2, (height - logo_img.height) // 2)
        else:
            logo_xy = (pad, (height - logo_img.height) // 2)
            text_x = pad + logo_img.width + pad
    text_w = width - text_x - pad
    fonts = [
        (text, _fit_font(text, text_w, round(inner_h * share)))
        for text, share in _lines(layout, title, domain)
    ]
    heights = [font.getbbox(text)[3] for text, font in fonts]
    gap = round(inner_h * 0.06)
    y = (height - (sum(heights) + gap * max(0, len(fonts) - 1))) // 2
    placed = []
    for (text, font), line_h in zip(fonts, heights, strict=True):
        x = (
            (width - round(font.getlength(text))) // 2
            if layout == LAYOUT_TITLE
            else text_x
        )
        placed.append((text, font, x, y))
        y += line_h + gap
    return logo_img, logo_xy, placed


def render_png(
    logo_path: str | None,
    title: str,
    domain: str,
    fill: str,
    stroke: str,
    width: int,
    height: int,
    layout: str,
) -> bytes:
    """Render one lockup as a transparent PNG.

    Args:
        logo_path: Logo file, or ``None`` for text-only layouts.
        title: Title text.
        domain: Domain shown by the domain layouts.
        fill: Text color.
        stroke: Text outline color.
        width: Output width.
        height: Output height.
        layout: One of the ``LAYOUT_*`` constants.

    Returns:
        PNG bytes.
    """
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    logo_img, logo_xy, placed = _compose(
        logo_path, title, domain, width, height, layout
    )
    if logo_img is not None:
        canvas.alpha_composite(logo_img, logo_xy)
    draw = ImageDraw.Draw(canvas)
    for text, font, x, y in placed:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=max(1, round(font.size * 0.08)),
            stroke_fill=stroke,
        )
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_svg(
    logo_path: str | None,
    title: str,
    domain: str,
    fill: str,
    stroke: str,
    width: int,
    height: int,
    layout: str,
) -> str:
    """Render one lockup as SVG with the logo embedded as PNG.

    ``textLength`` pins each line to the width measured with the PNG font, so
    the browser's own font cannot overflow the slot.

    Args:
        logo_path: Logo file, or ``None`` for text-only layouts.
        title: Title text.
        domain: Domain shown by the domain layouts.
        fill: Text color.
        stroke: Text outline color.
        width: Output width.
        height: Output height.
        layout: One of the ``LAYOUT_*`` constants.

    Returns:
        SVG document.
    """
    logo_img, logo_xy, placed = _compose(
        logo_path, title, domain, width, height, layout
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    ]
    if logo_img is not None:
        scale = min(2.0, _SVG_RASTER_MAX / max(logo_img.width, logo_img.height))
        crisp = _fit(
            _trimmed_logo(logo_path),
            round(logo_img.width * scale),
            round(logo_img.height * scale),
        )
        data = io.BytesIO()
        crisp.save(data, format="PNG", optimize=True)
        href = base64.b64encode(data.getvalue()).decode("ascii")
        parts.append(
            f'<image x="{logo_xy[0]}" y="{logo_xy[1]}" width="{logo_img.width}" height="{logo_img.height}" '
            f'href="data:image/png;base64,{href}"/>'
        )
    for text, font, x, y in placed:
        ascent = font.getmetrics()[0]
        parts.append(
            f'<text x="{x}" y="{y + ascent}" font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" '
            f'font-size="{font.size}" font-weight="600" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{max(1, round(font.size * 0.08))}" stroke-linejoin="round" paint-order="stroke" '
            f'textLength="{round(font.getlength(text))}" lengthAdjust="spacingAndGlyphs">{escape(text)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_favicon(logo_path: str) -> bytes:
    """Render the logo as a multi-size ICO.

    Args:
        logo_path: Logo file.

    Returns:
        ICO bytes.
    """
    square = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    logo = _fit(_trimmed_logo(logo_path), 256, 256)
    square.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
    out = io.BytesIO()
    square.save(out, format="ICO", sizes=FAVICON_SIZES)
    return out.getvalue()


def render_assets(
    logo_path: str,
    title: str | bool,
    domain: str,
    fill: str,
    stroke: str,
    frame_fill: str,
    frame_stroke: str,
    slots: dict[str, dict],
) -> dict[str, bytes]:
    """Render every slot as PNG and SVG plus ``favicon.ico``.

    Args:
        logo_path: Logo file.
        title: Title text, or ``False`` when titles are disabled.
        domain: Role domain.
        fill: Text color of a slot on a page or panel.
        stroke: Text outline color of a slot on a page or panel.
        frame_fill: Text color of a slot on brand-colored chrome.
        frame_stroke: Text outline color of a slot on brand-colored chrome.
        slots: ``{name: {"width", "height", "text_only", "frame"}}``.

    Returns:
        ``{filename: content}``.
    """
    has_title = bool(title)
    assets = {"favicon.ico": render_favicon(logo_path)}
    for name, spec in slots.items():
        layout = choose_layout(
            spec["width"], spec["height"], spec["text_only"], has_title
        )
        if layout == LAYOUT_TITLE and not has_title:
            continue
        args = (
            logo_path,
            str(title),
            domain,
            frame_fill if spec["frame"] else fill,
            frame_stroke if spec["frame"] else stroke,
            spec["width"],
            spec["height"],
            layout,
        )
        assets[f"{name}.png"] = render_png(*args)
        assets[f"{name}.svg"] = render_svg(*args).encode("utf-8")
    return assets
