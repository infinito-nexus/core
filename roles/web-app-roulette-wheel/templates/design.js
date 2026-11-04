(function () {
  const root = document.documentElement;
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  const BUSY = "rgb(192, 192, 192)";
  const SEGMENTS = [
    "rgba(255, 0, 0, 0.5)",
    "rgba(0, 255, 0, 0.5)",
    "rgba(0, 0, 255, 0.5)",
    "rgba(255, 255, 0, 0.5)",
    "rgba(0, 255, 255, 0.5)",
    "rgba(205, 127, 50, 0.5)",
    "rgba(115, 147, 179, 0.5)",
    "rgba(255, 117, 24, 0.5)",
    "rgba(255, 0, 255, 0.5)",
    "rgba(191, 64, 191, 0.5)",
    "rgba(47, 197, 114, 0.5)",
    "rgba(255, 222, 173, 0.5)",
    "rgba(204, 204, 255, 0.5)",
    "rgba(93, 63, 211, 0.5)",
    "rgba(250, 128, 114, 0.5)",
    "rgba(0, 255, 127, 0.5)"
  ];
  const FILLS = [
    "frame", "danger-active", "warning-active", "info-active", "frame-active", "primary-hover",
    "success-hover", "danger-hover", "warning-hover", "info-hover", "frame-hover", "primary",
    "success", "danger", "warning", "info"
  ];
  const POINTER = "#c4b454";
  const LABEL = "#000000";
  const DRAWS = ["clearRect", "beginPath", "save", "restore", "translate", "rotate", "lineTo", "arc", "fill", "stroke", "fillText"];
  let palette = null;
  let frame = [];
  let replaying = false;
  let label = null;
  function wheel(context) {
    return Boolean(context.canvas && context.canvas.closest && context.canvas.closest(".roulette-wheel"));
  }
  function tokens() {
    if (palette === null) {
      const probe = document.createElement("span");
      const read = function (name) {
        probe.style.color = `var(--design-${  name  })`;
        return getComputedStyle(probe).color;
      };
      (document.body || root).appendChild(probe);
      palette = { fill: {}, on: {}, pointer: read("primary"), line: read("border-strong") };
      FILLS.forEach(function (name) {
        palette.fill[name] = read(name);
        palette.on[name] = read(`on-${  name.replace(/-(hover|active)$/, "")}`);
      });
      probe.remove();
    }
    return palette;
  }
  function recolor(context, name) {
    const colors = tokens();
    if (name === "fill") {
      const slot = SEGMENTS.indexOf(context.fillStyle);
      if (slot !== -1) {
        context.fillStyle = colors.fill[FILLS[slot]];
        label = colors.on[FILLS[slot]];
      } else if (context.fillStyle === POINTER) {
        context.fillStyle = colors.pointer;
      }
    } else if (name === "fillText" && context.fillStyle === LABEL && label !== null) {
      context.fillStyle = label;
    } else if (name === "stroke") {
      context.strokeStyle = colors.line;
    }
  }
  if (window.CanvasRenderingContext2D) {
    DRAWS.forEach(function (name) {
      const proto = window.CanvasRenderingContext2D.prototype;
      const native = proto[name];
      proto[name] = function () {
        if (wheel(this)) {
          if (!replaying) {
            if (name === "clearRect") {
              frame = [];
            }
            frame.push([name, Array.prototype.slice.call(arguments), this.fillStyle, this.font]);
          }
          recolor(this, name);
        }
        return native.apply(this, arguments);
      };
    });
  }
  function repaint() {
    palette = null;
    const canvas = document.querySelector(".roulette-wheel canvas");
    if (!canvas || frame.length === 0) {
      return;
    }
    const context = canvas.getContext("2d");
    replaying = true;
    frame.forEach(function (draw) {
      context.fillStyle = draw[2];
      context.font = draw[3];
      context[draw[0]].apply(context, draw[1]);
    });
    replaying = false;
  }
  function effective() {
    const chosen = root.getAttribute("data-design-theme");
    if (chosen === "light" || chosen === "dark") {
      return chosen;
    }
    return dark.matches ? "dark" : "light";
  }
  function icon() {
    const image = document.querySelector(".light-dark-mode img.moon-sun");
    const wanted = effective() === "light" ? "static/sun.png" : "static/moon.png";
    if (image && image.getAttribute("src") !== wanted) {
      image.setAttribute("src", wanted);
    }
  }
  function clean() {
    const body = document.body;
    if (body && (body.style.backgroundColor || body.style.color)) {
      body.style.removeProperty("background-color");
      body.style.removeProperty("color");
    }
    const buttons = document.querySelectorAll(".add-item-button, .remove-all-items-button");
    for (let index = 0; index < buttons.length; index += 1) {
      const button = buttons[index];
      const fill = button.style.getPropertyValue("background-color");
      if (!fill) {
        continue;
      }
      if (fill === BUSY) {
        button.setAttribute("data-design-busy", "true");
      } else {
        button.removeAttribute("data-design-busy");
      }
      button.style.removeProperty("background");
    }
    const rows = document.querySelectorAll(".menu-item");
    for (let row = 0; row < rows.length; row += 1) {
      const shade = FILLS[SEGMENTS.indexOf(rows[row].style.backgroundColor)];
      if (shade && rows[row].getAttribute("data-design-fill") !== shade) {
        rows[row].setAttribute("data-design-fill", shade);
      }
    }
  }
  function brand() {
  if (INFINITO_DESIGN.title) {
      document.title = INFINITO_DESIGN.title;
  }
  if (INFINITO_DESIGN.logo) {
      const href = INFINITO_DESIGN.urls.favicon.png;
      const links = document.querySelectorAll("link[rel~='icon']");
      for (let index = 0; index < links.length; index += 1) {
        if (links[index].getAttribute("href") !== href) {
          links[index].setAttribute("type", "image/png");
          links[index].setAttribute("href", href);
        }
      }
  }
  }
  document.addEventListener("click", function (event) {
    if (!event.target.closest || !event.target.closest(".light-dark-mode")) {
      return;
    }
    root.setAttribute("data-design-theme", effective() === "dark" ? "light" : "dark");
    clean();
    icon();
    repaint();
  });
  document.addEventListener("DOMContentLoaded", function () {
  if (INFINITO_DESIGN.title || INFINITO_DESIGN.logo) {
      brand();
  }
    clean();
    icon();
    new MutationObserver(clean).observe(document.body, {
      attributes: true,
      attributeFilter: ["style"],
      childList: true,
      subtree: true,
    });
  });
  dark.addEventListener("change", icon);
  dark.addEventListener("change", repaint);
})();
