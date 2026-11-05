const DEMO_APP = `
  <div class="full" style="background:#f5f6f9;color:#1b1f29;font:20px/1.3 system-ui,sans-serif">
    <div class="abs" style="left:0;top:0;bottom:0;width:240px;height:100%;background:#1b1f29;color:#cfd5e2;padding:28px 22px">◆ Nexus<br><br>Dashboard<br>Projects<br>Deploys</div>
    <div class="abs" style="left:240px;right:0;top:0;width:1200px;height:80px;background:#fff;border-bottom:1px solid #e3e6ee;padding:26px 32px;font-weight:700">Projects</div>
    <div class="abs" data-r style="left:290px;top:130px;width:560px;height:330px;background:#fff;border:1px solid #e3e6ee;border-radius:16px;padding:22px">Create project</div>
    <div class="abs" data-r style="left:290px;top:490px;width:560px;height:110px;background:#fff;border:1px solid #e3e6ee;border-radius:16px;padding:22px">Ready to ship <span style="float:right;background:#3b6cf5;color:#fff;border-radius:10px;padding:8px 18px">Deploy</span></div>
    <div class="abs" data-r style="left:890px;top:130px;width:500px;height:470px;background:#fff;border:1px solid #e3e6ee;border-radius:16px;padding:22px">Status</div>
    <div class="abs" data-r style="left:290px;top:630px;width:1100px;height:230px;background:#fff;border:1px solid #e3e6ee;border-radius:16px;padding:22px;color:#99a">Recent activity</div>
  </div>`;
const DEMO_RECTS = [{ x: 290, y: 130, w: 560, h: 330 }, { x: 690, y: 490, w: 220, h: 110 }, { x: 890, y: 130, w: 500, h: 470 }, { x: 290, y: 630, w: 1100, h: 230 }];
const DEMO_LINES = [{ t0: 0.3, t1: 3.9 }, { t0: 4.3, t1: 6.4 }, { t0: 6.8, t1: 10.2 }];
const DEMO_WORDS = "Deploy once and every service comes up green with TLS already in place".split(" ").map((w, i) => ({ w, t0: 0.4 + i * 0.42, t1: 0.78 + i * 0.42 }));

preset("reveal", {
  what: "Rise per word through the padded mask (mask reveal, ticket 07)",
  dur: 4,
  params: [["stagger", "Stagger (s)", 0, 0.2, 0.005], ["dur", "Duration (s)", 0.2, 1.4, 0.05]],
  html: () => `<div class="abs" style="left:120px;top:330px"><div data-k="line" class="t" style="font-size:96px;font-weight:800">Ship it. Öffnen. Égalité.</div></div>`,
  setup() { $.words = split($.line, "word", true); },
  frame(t, P) { reveal($.words, t, 0.5, P); return { started: $.words.filter((_, i) => t >= 0.5 + i * P.stagger).length }; },
});

preset("focus", {
  what: "Narration camera: glide to each line's focus rect, zoom from the rect size (ticket 06, variant A)",
  dur: 12,
  params: [["maxZoom", "Max zoom", 1, 3, 0.05], ["intensity", "Intensity", 0, 1.5, 0.05], ["ease", "Ease-in (s)", 0.2, 1.5, 0.05], ["damping", "Spring damping", 0.5, 1.2, 0.02], ["fill", "Fill", 0.5, 1, 0.01]],
  html: () => `<div data-k="cam" class="full">${DEMO_APP}</div>`,
  frame(t, P) {
    const cam = focus(t, DEMO_LINES.map((l, i) => ({ ...l, rect: DEMO_RECTS[i] })), P);
    applyFocus($.cam, cam);
    return { camera: { x: +cam.x.toFixed(1), y: +cam.y.toFixed(1), s: +cam.s.toFixed(3) } };
  },
});

preset("cursor", {
  what: "Bezier cursor with overshoot, click dip and ripple (ticket 06)",
  dur: 12,
  params: [["arc", "Arc", 0, 0.4, 0.01], ["overshoot", "Overshoot", 0, 0.15, 0.005], ["size", "Size (px)", 20, 60, 1], ["ripple", "Ripple radius", 20, 120, 2], ["dip", "Click dip", 0.6, 1, 0.01]],
  html: () => `${DEMO_APP}${cursorLayer()}`,
  frame(t, P) {
    const at = cursor(t, [{ t: 0, x: 1100, y: 700 }, { t: 0.9, x: 1330, y: 42, click: true }, { t: 1.8, x: 600, y: 268, click: true },
      { t: 2.9, x: 600, y: 372, click: true }, { t: 4.8, x: 790, y: 545, click: true }, { t: 7.6, x: 1150, y: 300 }, { t: 11, x: 1150, y: 300 }], P);
    return { cursor: { x: +at.x.toFixed(1), y: +at.y.toFixed(1), press: +at.press.toFixed(3) } };
  },
});

preset("captions", {
  what: "Kinetic captions, bounce in, 3-word pages, active word yellow (ticket 07)",
  dur: 7,
  params: [["perPage", "Words per page", 1, 6, 1], ["response", "Spring response", 0.15, 0.8, 0.01], ["damping", "Spring damping", 0.3, 1, 0.01], ["rise", "Rise (px)", 0, 100, 1], ["fromScale", "From scale", 0.5, 1, 0.01]],
  html: () => `<div class="full" style="background:linear-gradient(160deg,#25304a,#0b0e15)"></div>${captionLayer()}`,
  frame(t, P) { return { page: captions(t, DEMO_WORDS, { ...P, on: true }) }; },
});

preset("spotlight", {
  what: "Spring-glide spotlight moving between targets (ticket 07)",
  dur: 8,
  params: [["dim", "Dim", 0.2, 0.9, 0.02], ["padding", "Padding (px)", 0, 60, 1], ["radius", "Corner radius", 0, 60, 1], ["feather", "Feather (px)", 0, 40, 1], ["response", "Spring response", 0.2, 1.2, 0.01], ["damping", "Spring damping", 0.5, 1.1, 0.01]],
  html: () => `${DEMO_APP}${spotlightLayer()}`,
  frame(t, P) {
    const r = spotlight(t, [{ t: 0.6, rect: DEMO_RECTS[0] }, { t: 2.2, rect: DEMO_RECTS[2] }, { t: 3.8, rect: DEMO_RECTS[1] }, { t: 5.4, rect: DEMO_RECTS[3] }], [0.3, 7.2], P);
    return { rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) } };
  },
});

preset("emphasize", {
  what: "Callout label tied to a voice line (ticket 07)",
  dur: 11,
  params: [["lead", "Start after line start (s)", -0.4, 0.8, 0.05], ["response", "Spring response", 0.2, 1, 0.01], ["damping", "Spring damping", 0.4, 1.1, 0.01], ["fadeOut", "Fade out (s)", 0.1, 1, 0.05], ["stroke", "Stroke", 2, 14, 1]],
  html: () => `${DEMO_APP}${emphasizeLayer()}`,
  frame(t, P) {
    const i = DEMO_LINES.findIndex((l) => t >= l.t0 + P.lead && t <= l.t1 + P.fadeOut);
    const k = i < 0 ? 0 : i;
    const a = emphasize(t, DEMO_LINES[k], DEMO_RECTS[k], ["Name and domain", "One click", "All green"][k], P);
    return { line: i + 1, amount: +a.toFixed(3) };
  },
});

preset("morph", {
  what: "FLIP morph with content fade, source hidden (ticket 07)",
  dur: 7,
  params: [["response", "Spring response (s)", 0.25, 1.2, 0.01], ["damping", "Spring damping", 0.5, 1.1, 0.01], ["contentDelay", "Content fade-in delay (s)", 0, 0.8, 0.05]],
  html: () => `<div class="full" style="background:#f5f6f9;color:#1b1f29;font:600 26px system-ui">
    <div data-k="src" class="abs" style="left:80px;top:270px;width:400px;height:120px;background:#fff;border:1px solid #e3e6ee;border-radius:16px;padding:24px">mail-stack</div>
    <div data-k="mover" class="abs" style="overflow:hidden;background:#fff;border:1px solid #e3e6ee;padding:24px;box-shadow:0 30px 80px rgba(0,0,0,.18)">mail-stack
      <div data-k="body" style="font:400 24px system-ui;margin-top:30px;line-height:1.7;color:#556">Status: healthy<br>Domains: 3<br>Last deploy: 2 min ago</div></div></div>`,
  frame(t, P) {
    const p = morph(t, $.mover, { x: 80, y: 270, w: 400, h: 120, r: 16 }, { x: 560, y: 130, w: 800, h: 640, r: 24 }, 1.2, 5.2, { ...P, source: $.src, content: $.body });
    show($.mover, t >= 1.2 && p > 0.001);
    return { p: +p.toFixed(3) };
  },
});

preset("whip", {
  what: "Whip-push cut on the beat grid (ticket 07)",
  dur: 8,
  params: [["beats", "Transition (beats)", 0.1, 1, 0.05], ["blur", "Blur peak (px)", 0, 40, 1], ["every", "Cut every N beats", 1, 8, 1]],
  html: () => ["#3b6cf5", "#e2465c", "#13a36f", "#f0a020", "#7b4fd6", "#1aa3b8", "#3b6cf5", "#e2465c"].map((c, i) =>
    `<div data-k="shot${i}" class="full" style="background:${c};display:flex;align-items:center;justify-content:center;font:800 140px system-ui;color:#fff">Shot ${i + 1}</div>`).join(""),
  frame(t, P) {
    const shots = beatCuts([0, 1, 2, 3, 4, 5, 6, 7].map((i) => "shot" + i), 1, P);
    sequence(t, shots);
    return { beat: Math.floor(t / FILM.P) + 1, cutsAt: shots.map((s) => +s.t0.toFixed(2)).slice(0, 4) };
  },
});

preset("parallax", {
  what: "Side-pan parallax over three depth layers (ticket 07)",
  dur: 8,
  params: [["travel", "Camera travel (px)", 20, 400, 5]],
  html: () => `<div class="full" style="background:#0f1420">
    <div data-k="L0" class="abs" style="left:-200px;top:-150px;width:1840px;height:1200px;background-image:linear-gradient(#1c2638 2px,transparent 2px),linear-gradient(90deg,#1c2638 2px,transparent 2px);background-size:80px 80px"></div>
    <div data-k="L1" class="abs" style="left:-200px;top:-150px;width:1840px;height:1200px">${[[300, 300, "Logs"], [1300, 360, "Metrics"], [500, 850, "Alerts"]].map(([x, y, n]) =>
      `<div class="abs" style="left:${x}px;top:${y}px;width:380px;height:220px;opacity:.6;background:rgba(255,255,255,.92);border-radius:18px;font:700 28px system-ui;color:#1b1f29;padding:24px">${n}</div>`).join("")}</div>
    <div data-k="L2" class="abs" style="left:-200px;top:-150px;width:1840px;height:1200px"><div class="abs" style="left:620px;top:420px;width:600px;height:380px;background:rgba(255,255,255,.92);border-radius:18px;font:700 40px system-ui;color:#1b1f29;padding:24px">Dashboard</div></div></div>`,
  frame(t, P) { return { cx: +parallax([$.L0, $.L1, $.L2], t, 0, FILM.DURATION, P).toFixed(1) }; },
});

preset("tilt", {
  what: "Hero tilt-in of a device screen, gloss and contact shadow follow the angle (ticket 07)",
  dur: 6,
  params: [["angle", "Max angle (°)", 4, 40, 1], ["perspective", "Perspective (px)", 800, 4000, 50], ["gloss", "Gloss", 0, 0.8, 0.02], ["response", "Spring response", 0.4, 2, 0.05], ["rise", "Rise (px)", 0, 400, 10]],
  html: () => `<div class="full" style="background:radial-gradient(circle at 50% 30%,#2a3348,#0b0e15)">
    <div data-k="shadow" class="abs" style="left:50%;top:750px;width:900px;height:80px;margin-left:-450px;border-radius:50%;background:radial-gradient(rgba(0,0,0,.55),transparent 70%)"></div>
    <div data-k="wrap" class="full"><div data-k="screen" class="abs" style="left:50%;top:50%;width:960px;height:600px;margin:-300px 0 0 -480px;border-radius:22px;background:#f5f6f9;border:14px solid #15181f;overflow:hidden">
      <div style="height:56px;background:#fff;border-bottom:1px solid #e3e6ee;padding:14px 22px;font:700 22px system-ui;color:#1b1f29">◆ Nexus · Projects</div>
      <div data-k="gloss" class="full"></div></div></div></div>`,
  frame(t, P) { const r = tilt(t, 0.2, { wrap: $.wrap, screen: $.screen, gloss: $.gloss, shadow: $.shadow }, P); return { rotateX: +r.rx.toFixed(2), rotateY: +r.ry.toFixed(2) }; },
});

preset("chart", {
  what: "Bars with count-up labels, staggered springs (ticket 07)",
  dur: 4,
  params: [["stagger", "Stagger (s)", 0, 0.4, 0.01], ["response", "Spring response", 0.2, 1.6, 0.05], ["damping", "Spring damping", 0.5, 1.1, 0.01]],
  html: () => `<div class="full" style="background:#f5f6f9;--ink:#1b1f29;--ink2:#667;--accent:#3b6cf5"><svg data-k="chart" class="full" viewBox="0 0 1440 900" style="font-family:system-ui"></svg></div>`,
  frame(t, P) { chart($.chart, t, 0.4, [22, 35, 31, 48, 56, 63, 74, 92], { ...P, labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Now"] }); return {}; },
});

preset("aurora", {
  what: "Aurora background: four radial-gradient blobs on sine paths, no CSS blur (ticket 07)",
  dur: 8,
  params: [["speed", "Speed", 0.1, 3, 0.05], ["size", "Blob size", 0.4, 2, 0.05], ["intensity", "Intensity", 0.2, 1, 0.05]],
  html: () => `<div class="full" style="background:#07080d"></div>${auroraLayer()}<div class="full" style="display:flex;align-items:center;justify-content:center;font:800 110px system-ui;color:#fff">Infinito Nexus</div>`,
  frame(t, P) { aurora(t, P); return {}; },
});

preset("motionBlur", {
  what: "Sub-frame accumulation: samples across a part-frame shutter, each at gain/n opacity; off in preview (ticket 07)",
  dur: 4,
  W: 1440,
  H: 1440,
  params: [["samples", "Samples", 2, 16, 1], ["shutter", "Shutter (frames)", 0, 1, 0.05], ["gain", "Opacity gain", 1, 2.5, 0.05]],
  html: () => `<div class="full" style="background:#0b0e15"></div><div data-k="host" class="full"><div class="abs" style="top:460px;width:520px;height:520px;background:#fff;border-radius:22px;box-shadow:0 30px 80px rgba(0,0,0,.4);font:700 40px system-ui;color:#1b1f29;padding:30px">Deploy</div></div>`,
  frame(t, P) {
    const pos = (u) => lerp(160, 1440 - 160 - 520, prog(u, 0.8, 0.9)) + lerp(0, -(1440 - 640), prog(u, 2.4, 0.9));
    motionBlur($.host, t, (el, u) => { el.style.left = pos(u).toFixed(2) + "px"; }, P);
    return { samples: $.host.children.length };
  },
});

preset("rackFocus", {
  what: "Rack focus: CSS blur per depth layer, focus shifts back to front (ticket 07)",
  dur: 4,
  W: 1440,
  H: 1440,
  params: [["maxBlur", "Max blur (px)", 0, 30, 1], ["shift", "Shift time (s)", 0.4, 3, 0.1]],
  html: () => `<div class="full" style="background:#0b0e15"></div>` + [[120, 160, 0.6, "Back"], [460, 480, 0.8, "Middle"], [840, 820, 1, "Front"]].map(([x, y, s, n], i) =>
    `<div data-k="d${i}" class="abs" style="left:${x}px;top:${y}px;width:${480 * s}px;height:${360 * s}px;background:#fff;border-radius:22px;font:700 40px system-ui;color:#1b1f29;padding:30px">${n}</div>`).join(""),
  frame(t, P) { return { focusLayer: +rackFocus([$.d0, $.d1, $.d2], t, 1, 2, 0, P).toFixed(2) }; },
});
