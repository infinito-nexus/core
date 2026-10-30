film({ W: 1920, H: 1080, BPM: 110.0, BEATS: 112 });

const SHOTS = [];
const BOXES = ["alejandro@infinito.test", "maria@infinito.test", "info@infinito.test"];
const CARD_T = [B(21), B(24), B(27)];
const CARD_DUR = 1.9;
const ICON_FOLDER = '<path d="M8 28 V80 H92 V36 H48 L40 26 H8 Z"/>';
const ICON_FLAG = '<path d="M22 92 V10"/><path d="M22 14 H82 L70 34 L82 54 H22"/>';
const ICON_DATE = '<rect x="10" y="18" width="80" height="70" rx="8"/><path d="M10 40 H90 M32 8 V26 M68 8 V26"/>';
const ICON_MAIL = '<rect x="8" y="20" width="84" height="60" rx="8"/><path d="M10 24 L50 54 L90 24"/>';
const ICON_DB = '<ellipse cx="50" cy="20" rx="36" ry="12"/><path d="M14 20 V80 C14 96 86 96 86 80 V20 M14 50 C14 66 86 66 86 50"/>';
const FEATURES = [
  { k: "fFolder", label: "Folders", icon: ICON_FOLDER, at: B(25) },
  { k: "fFlag", label: "Read flags", icon: ICON_FLAG, at: B(29) },
  { k: "fDate", label: "Dates", icon: ICON_DATE, at: B(31) },
];
const LINES = [
  { k: "l1", text: "Your mail,", at: B(74) },
  { k: "l2", text: "your calendars,", at: B(76) },
  { k: "l3", text: "your contacts,", at: B(78) },
];

const kicker = (k, text, x, y, w) =>
  `<div class="abs mask" style="left:${x}px;top:${y}px;width:${w}px;height:38px"><div data-k="${k}" class="t kicker">${text}</div></div>`;
const svgIcon = (body, size, stroke = "var(--ink)", sw = 7) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 100 100" fill="none" stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round">${body}</svg>`;

const box = (k, name, x, accent) => `
  <div data-k="${k}" class="abs" style="left:${x}px;top:330px;width:500px;height:440px;border:3px solid ${accent ? "var(--accent2)" : "var(--ink3)"};border-radius:24px;background:var(--bg2)">
    <div class="abs t" style="left:36px;top:26px;font-size:54px;font-weight:800;color:${accent ? "var(--ink)" : "var(--ink2)"}">${name}</div>
    ${BOXES.map((b, i) => `
      <div data-k="${k}Row${i}" class="abs row" style="left:30px;top:${126 + i * 92}px;width:440px;height:76px;border-radius:12px;border:2px solid var(--hair);background:${accent ? "rgba(79,107,255,0.10)" : "rgba(239,239,239,0.04)"};padding-left:20px;gap:16px">
        ${svgIcon(ICON_MAIL, 34, accent ? "var(--accent2)" : "var(--ink2)")}
        <div class="t mono" style="font-size:23px;color:var(--ink)">${b}</div>
      </div>`).join("")}
  </div>`;

function build(stage) {
  stage.innerHTML = `
    <div class="full" data-k="world">
      <div class="shot" data-k="s1">
        ${kicker("k1", "09 · MOVING FROM MAILU", 260, 380, 1400)}
        <div class="abs mask" style="left:260px;top:440px;width:1500px;height:160px"><div data-k="t1a" class="t h1">On Mailu today?</div></div>
        <div class="abs mask" style="left:260px;top:620px;width:1500px;height:80px"><div data-k="t1b" class="t" style="font-size:64px;font-weight:500;color:var(--ink2)">There's a built-in import<span style="color:var(--accent2)">.</span></div></div>
      </div>

      <div class="shot" data-k="s2">
        ${kicker("k2", "09 · MOVING FROM MAILU", 200, 100, 1000)}
        ${box("mailu", "Mailu", 200, false)}
        ${box("stal", "Stalwart", 1220, true)}
        <div data-k="sw" class="abs" style="left:760px;top:640px;width:400px;height:110px">
          <div class="abs center" style="left:0;top:0;width:400px;height:40px"><div data-k="swLabel" class="t mono" style="font-size:24px;color:var(--ink2)">import_mailu: false</div></div>
          <div data-k="swTrack" class="abs" style="left:150px;top:52px;width:100px;height:52px;border-radius:26px;background:var(--ink3)">
            <div data-k="swKnob" class="abs" style="left:6px;top:6px;width:40px;height:40px;border-radius:50%;background:var(--ink)"></div>
          </div>
        </div>
        ${BOXES.map((b, i) => `
          <div data-k="card${i}" class="abs row" style="left:0;top:0;width:420px;height:84px;border-radius:16px;border:2px solid var(--accent2);background:#141B3D;padding:0 18px;gap:14px;opacity:0">
            ${svgIcon(ICON_MAIL, 36, "var(--ink)")}
            <div class="t mono" style="font-size:21px;color:var(--ink);flex:1">${b.split("@")[0]}</div>
            ${svgIcon(ICON_FOLDER, 30, "var(--accent2)", 8)}${svgIcon(ICON_FLAG, 30, "var(--accent2)", 8)}${svgIcon(ICON_DATE, 30, "var(--accent2)", 8)}
          </div>`).join("")}
        <svg class="abs" style="left:0;top:0;overflow:visible" width="1920" height="1080" viewBox="0 0 1920 1080" fill="none">
          <path data-k="loop" d="M1470 320 C1440 170 1230 150 960 150 C690 150 480 170 450 320" stroke="var(--accent2)" stroke-width="7" stroke-linecap="round"/>
          <path data-k="loopHead" d="M426 292 L450 324 L478 296" stroke="var(--accent2)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="abs center" style="left:560px;top:180px;width:800px;height:110px;flex-direction:column">
          <div class="mask" style="height:58px"><div data-k="again" class="t" style="font-size:44px;font-weight:800">Run it again. And again.</div></div>
          <div class="mask" style="height:29px;margin-top:8px"><div data-k="again2" class="t mono" style="font-size:24px;color:var(--ink2)">already moved = skipped, never duplicated</div></div>
        </div>
        ${FEATURES.map((f, i) => `
          <div data-k="${f.k}" class="abs row" style="left:${470 + i * 360}px;top:850px;gap:20px">
            ${svgIcon(f.icon, 56, "var(--accent2)")}
            <div class="t" style="font-size:42px;font-weight:800">${f.label}</div>
          </div>`).join("")}
      </div>

      <div class="shot center" data-k="s3">
        <div data-k="warn" class="abs" style="left:410px;top:230px;width:1100px;height:620px;border:3px solid #F5B83D;border-radius:28px;background:var(--bg2)">
          ${kicker("k3", "15.0 IS A MAJOR RELEASE", 70, 60, 900)}
          <svg data-k="tri" class="abs" style="left:70px;top:130px" width="120" height="110" viewBox="0 0 100 92" fill="none" stroke="#F5B83D" stroke-width="7" stroke-linejoin="round" stroke-linecap="round"><path d="M50 6 L94 86 H6 Z"/><path d="M50 34 V58 M50 70 V72"/></svg>
          <div class="abs mask" style="left:220px;top:130px;width:840px;height:102px"><div data-k="bu" class="t" style="font-size:84px;font-weight:800;letter-spacing:-0.03em">Before You Upgrade</div></div>
          <div class="abs mask" style="left:72px;top:280px;width:980px;height:47px"><div data-k="bu2" class="t" style="font-size:38px;font-weight:500;color:var(--ink2)">Read this section of the release article first.</div></div>
          <div data-k="cPg" class="abs row" style="left:72px;top:400px;width:450px;height:150px;border:2px solid var(--hair);border-radius:20px;padding-left:34px;gap:26px">
            ${svgIcon(ICON_DB, 72, "#F5B83D")}<div class="t" style="font-size:46px;font-weight:800">PostgreSQL</div>
          </div>
          <div data-k="cMail" class="abs row" style="left:578px;top:400px;width:450px;height:150px;border:2px solid var(--hair);border-radius:20px;padding-left:34px;gap:26px">
            ${svgIcon(ICON_MAIL, 72, "#F5B83D")}<div class="t" style="font-size:46px;font-weight:800">Mail</div>
          </div>
        </div>
      </div>

      <div class="shot" data-k="s4">
        ${LINES.map((l, i) => `
          <div class="abs mask" style="left:260px;top:${210 + i * 150}px;width:1400px;height:140px"><div data-k="${l.k}" class="t h1" style="font-size:116px">${l.text}</div></div>`).join("")}
        <div class="abs mask" style="left:260px;top:700px;width:1500px;height:88px"><div data-k="l4" class="t" style="font-size:72px;font-weight:800;color:var(--accent2)">on your own infrastructure.</div></div>
        <div data-k="l4u" class="abs" style="left:262px;top:820px;width:1020px;height:8px;border-radius:4px;background:var(--accent2);transform-origin:0 50%"></div>
      </div>

      <div class="shot center" data-k="s5" style="flex-direction:column;gap:30px">
        <img data-k="logo" src="${ASSETS.img.logo}" style="width:240px;height:240px;border-radius:50%">
        <div data-k="title" class="t mono" style="font-size:60px">Infinito.Nexus 15.0</div>
        <div data-k="thanks" class="t" style="font-size:44px;font-weight:500;color:var(--ink2)">Thanks for watching.</div>
        <div data-k="credit" class="abs center" style="left:0;top:980px;width:1920px;height:40px"><div class="t" style="font-size:22px;color:var(--ink3)">Music: “Industrial Cinematic” by Kevin MacLeod (incompetech.com), CC BY 4.0</div></div>
      </div>
    </div>
    ${scanLayer(0.06)}
    ${vignetteLayer(0.5)}
    ${grainLayer(0.08)}`;
  collect(stage);
  SHOTS.push(
    { k: "s1", t0: 0 },
    { k: "s2", t0: B(9), join: ["push", 0.55, { dir: "up" }] },
    { k: "s3", t0: B(49), join: ["cover", 0.55, { dir: "left" }] },
    { k: "s4", t0: B(73), join: ["push", 0.55, { dir: "up" }] },
    { k: "s5", t0: B(89), join: ["dissolve", 0.6] },
  );
}

function apply(t) {
  sequence(t, SHOTS);
  grain(t);
  scan(t, (4 * Math.round(10 * FILM.DURATION)) / FILM.DURATION);

  rise($.k1, prog(t, 0.3, 0.5, E.out));
  rise($.t1a, prog(t, 0.6, 0.6, E.out));
  rise($.t1b, prog(t, B(5), 0.6, E.out));

  rise($.k2, prog(t, B(9) + 0.3, 0.5, E.out));
  const mIn = spring(t, B(10), 0.4, 0.8);
  $.mailu.style.opacity = clamp(mIn * 1.5).toFixed(3);
  setT($.mailu, `translateY(${(60 * (1 - mIn)).toFixed(1)}px)`);
  const sIn = spring(t, B(13), 0.4, 0.8);
  $.stal.style.opacity = clamp(sIn * 1.5).toFixed(3);
  setT($.stal, `translateY(${(60 * (1 - sIn)).toFixed(1)}px)`);

  const swIn = prog(t, B(16), 0.4, E.out);
  $.sw.style.opacity = swIn.toFixed(3);
  const flip = spring(t, B(18), 0.25, 0.7);
  setT($.swKnob, `translateX(${(48 * flip).toFixed(1)}px)`);
  $.swTrack.style.background = flip > 0.5 ? "var(--accent2)" : "var(--ink3)";
  $.swLabel.textContent = flip > 0.5 ? "import_mailu: true" : "import_mailu: false";
  $.swLabel.style.color = flip > 0.5 ? "var(--ink)" : "var(--ink2)";

  BOXES.forEach((_, i) => {
    const p = clamp((t - CARD_T[i]) / CARD_DUR);
    const e = E.inOut(p);
    const x = 230 + (1250 - 230) * e;
    const s = Math.sin(Math.PI * e);
    const y = (456 + i * 92) * (1 - s) + 250 * s;
    const vis = p <= 0 || p >= 1 ? 0 : clamp(Math.min(p, 1 - p) * 8);
    const c = $["card" + i];
    c.style.opacity = vis.toFixed(3);
    setT(c, `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`);
    $["mailuRow" + i].style.opacity = (1 - 0.65 * clamp(p * 4)).toFixed(3);
    const land = clamp((p - 0.85) / 0.15);
    $["stalRow" + i].style.opacity = (0.15 + 0.85 * land).toFixed(3);
  });

  FEATURES.forEach((f) => {
    const p = spring(t, f.at, 0.35, 0.8);
    $[f.k].style.opacity = clamp(p * 1.6).toFixed(3);
    setT($[f.k], `translateY(${(40 * (1 - p)).toFixed(1)}px)`);
  });

  const loopP = prog(t, B(37), 1.2, E.inOut);
  drawPath($.loop, loopP);
  $.loopHead.style.opacity = loopP > 0.97 ? "1" : "0";
  const spin = t > B(41) ? 0.5 + 0.5 * Math.cos((t - B(41)) * 2.2) : 1;
  $.loop.style.opacity = (0.6 + 0.4 * spin).toFixed(3);
  rise($.again, prog(t, B(38), 0.5, E.out));
  rise($.again2, prog(t, B(43), 0.5, E.out));

  const wIn = spring(t, B(49) + 0.2, 0.45, 0.8);
  setT($.warn, `scale(${(0.92 + 0.08 * wIn).toFixed(4)})`);
  rise($.k3, prog(t, B(50), 0.5, E.out));
  const triP = spring(t, B(53), 0.3, 0.6);
  $.tri.style.opacity = clamp(triP * 2).toFixed(3);
  setT($.tri, `scale(${(0.5 + 0.5 * triP).toFixed(4)})`);
  rise($.bu, prog(t, B(54), 0.55, E.out));
  rise($.bu2, prog(t, B(58), 0.55, E.out));
  [["cPg", B(66)], ["cMail", B(68)]].forEach(([k, at]) => {
    const p = spring(t, at, 0.35, 0.8);
    $[k].style.opacity = clamp(p * 1.6).toFixed(3);
    setT($[k], `translateY(${(40 * (1 - p)).toFixed(1)}px)`);
    $[k].style.borderColor = p > 0.5 ? "#F5B83D" : "var(--hair)";
  });

  LINES.forEach((l) => rise($[l.k], prog(t, l.at, 0.55, E.out)));
  rise($.l4, prog(t, B(81), 0.6, E.out));
  setT($.l4u, `scaleX(${prog(t, B(82), 0.8, E.inOut).toFixed(4)})`);

  const end = spring(t, B(89) + 0.2, 0.5, 0.85);
  const out = prog(t, B(107), FILM.DURATION - B(107) - 0.15, E.in);
  const fade = 1 - out;
  $.logo.style.opacity = (clamp(end * 1.4) * fade).toFixed(3);
  setT($.logo, `scale(${(0.8 + 0.2 * end).toFixed(4)})`);
  $.title.style.opacity = (prog(t, B(90), 0.6, E.out) * fade).toFixed(3);
  $.thanks.style.opacity = (prog(t, B(92), 0.6, E.out) * fade).toFixed(3);
  $.credit.style.opacity = (prog(t, B(95), 0.8, E.out) * fade).toFixed(3);
}
