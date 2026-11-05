const PHONE = { W: 402, H: 874, R: 55, bezel: 5, frame: 3 };
const FULL = { x: 0, y: 0, w: PHONE.W, h: PHONE.H, r: PHONE.R };
const BUTTONS = [[-1, 142, 28], [-1, 212, 50], [-1, 276, 50], [1, 238, 98]];

function deviceMarkup(appHtml) {
  const bar = (w, h) => `<div style="width:${w}px;height:${h}px;border-radius:1px;background:var(--sb)"></div>`;
  return `
    <div class="cam" data-k="device">
      <div class="abs" data-k="devShadow"></div>
      ${BUTTONS.map((_, i) => `<div class="abs" data-k="btn${i}" style="background:linear-gradient(90deg,#1E2320,#3A403B 50%,#1E2320)"></div>`).join("")}
      <div class="abs" data-k="devBody" style="background:linear-gradient(145deg,#4A504B 0%,#262B27 22%,#1A1E1B 50%,#2B302C 78%,#454B46 100%);box-shadow:inset 0 0 0 0.6px rgba(255,255,255,.22)">
        <div class="abs" data-k="devBezel" style="background:#070807"></div></div>
      <div class="screen" data-k="screen">
        ${appHtml}
        <div class="screen" data-k="overlay" style="--sb:var(--ink)">
          <div class="abs t" style="left:52px;top:15px;width:60px;text-align:center;font-size:17px;font-weight:600;color:var(--sb)">9:41</div>
          <div class="abs row" style="right:28px;top:22px;gap:3px;align-items:flex-end">${bar(3, 5)}${bar(3, 7)}${bar(3, 9)}${bar(3, 11)}
            <div style="width:25px;height:12px;margin-left:6px;border-radius:4px;border:1.5px solid var(--sb);padding:1.5px"><div style="width:100%;height:100%;border-radius:2px;background:var(--sb)"></div></div></div>
          <div class="abs" style="left:138.5px;top:11px;width:125px;height:37px;border-radius:999px;background:#050605"></div>
          <div class="abs" data-k="homeInd" style="left:134px;top:861px;width:134px;height:5px;border-radius:3px;background:var(--sb)"></div>
        </div>
      </div>
    </div>`;
}

function placeDevice(cam, rect, edge, buttons) {
  setT($.device, T(cam.x, cam.y, cam.s));
  $.screen.style.clipPath = `inset(${rect.y.toFixed(2)}px ${(PHONE.W - rect.x - rect.w).toFixed(2)}px ${(PHONE.H - rect.y - rect.h).toFixed(2)}px ${rect.x.toFixed(2)}px round ${rect.r.toFixed(2)}px)`;
  const e = (PHONE.bezel + PHONE.frame) * edge, b = PHONE.bezel * edge;
  const body = { x: rect.x - e, y: rect.y - e, w: rect.w + 2 * e, h: rect.h + 2 * e, r: rect.r + e };
  rectCss($.devBody, body);
  rectCss($.devShadow, body);
  rectCss($.devBezel, { x: e - b, y: e - b, w: rect.w + 2 * b, h: rect.h + 2 * b, r: rect.r + b });
  $.devShadow.style.boxShadow = `0 ${(26 * edge).toFixed(2)}px ${(50 * edge).toFixed(2)}px rgba(20,26,21,${(0.2 * edge).toFixed(3)})`;
  show($.devBody, edge > 0.001);
  show($.devShadow, edge > 0.001);
  BUTTONS.forEach(([side, y, h], i) => {
    const w = 3.2 * buttons, k = rect.h / PHONE.H;
    rectCss($["btn" + i], { x: side < 0 ? rect.x - e - w + 0.6 : rect.x + rect.w + e - 0.6, y: rect.y + y * k, w, h: h * k, r: 1.4 });
    show($["btn" + i], buttons > 0.01);
  });
}

const camAt = (s, top) => ({ s, x: FILM.W / 2 - (PHONE.W / 2) * s, y: -top * s });
const camMix = (a, b, p) => ({ s: lerp(a.s, b.s, p), x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p) });

function drifted(c, since, rate = 0.008) {
  const k = 1 + rate * Math.max(0, since);
  return { s: c.s * k, x: FILM.W / 2 - (FILM.W / 2 - c.x) * k, y: FILM.H / 2 - (FILM.H / 2 - c.y) * k };
}

function cameraAt(shots, t) {
  let i = 0;
  while (i + 1 < shots.length && t >= shots[i + 1].t0) i++;
  const at = (k) => drifted(shots[k].cam, t - (shots[k].rest ?? shots[k].t0 + shots[k].d));
  return i ? camMix(at(i - 1), at(i), prog(t, shots[i].t0, shots[i].d, E.smooth)) : at(0);
}
