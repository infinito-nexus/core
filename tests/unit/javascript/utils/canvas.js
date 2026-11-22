const UNPARSEABLE_COLOUR = "not-a-colour";

function parseColour(value) {
  const text = String(value).trim().toLowerCase();
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((digit) => digit + digit) : hex[1].match(/../g);
    return [...digits.map((pair) => parseInt(pair, 16)), 255];
  }
  const rgb = text.match(/^rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)$/);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3]), Math.round(255 * Number(rgb[4] ?? 1))];
  return null;
}

/**
 * Canvas 2D context double.
 *
 * Returns:
 *   The context of a 1x1 canvas whose fillStyle starts black, ignores a colour it cannot parse, and is saved and restored with the drawing state.
 */
function canvasContext() {
  const saved = [];
  let fill = [0, 0, 0, 255];
  let pixel = [0, 0, 0, 0];
  return {
    get fillStyle() {
      return `rgba(${fill.join(", ")})`;
    },
    set fillStyle(value) {
      fill = parseColour(value) ?? fill;
    },
    save: () => saved.push(fill),
    restore: () => {
      if (saved.length > 0) fill = saved.pop();
    },
    clearRect: () => {
      pixel = [0, 0, 0, 0];
    },
    fillRect: () => {
      pixel = [...fill];
    },
    getImageData: () => ({ data: Uint8ClampedArray.from(pixel) }),
  };
}

/**
 * Args:
 *   css: computed value per kebab-case property, e.g. `{ color: "rgb(0, 0, 0)" }`.
 *   parentElement: the element's parent, or null.
 *
 * Returns:
 *   A visible element double.
 */
function styledElement(css, parentElement) {
  return { css, parentElement, getClientRects: () => [{}] };
}

/**
 * Args:
 *   tokens: value per design token, e.g. `{ "--design-link": "rgb(0, 0, 255)" }`.
 *   elements: element per selector `document.querySelector` resolves.
 *
 * Returns:
 *   The `document` and `getComputedStyle` globals the colour samplers read; a probe styled with `var(token)` computes to the token's value.
 */
function browserGlobals(tokens, elements) {
  const createElement = (tag) => {
    if (tag === "canvas") return { getContext: () => canvasContext() };
    const css = {};
    return {
      css,
      style: { setProperty: (property, value) => (css[property] = tokens[value.slice(4, -1)]) },
      remove: () => undefined,
    };
  };
  return {
    document: {
      body: { appendChild: () => undefined },
      createElement,
      querySelector: (selector) => elements[selector] ?? null,
    },
    getComputedStyle: (element) => ({
      visibility: "visible",
      color: element.css.color,
      backgroundColor: element.css["background-color"],
      getPropertyValue: (property) => element.css[property] ?? "",
    }),
  };
}

module.exports = { UNPARSEABLE_COLOUR, browserGlobals, canvasContext, styledElement };
