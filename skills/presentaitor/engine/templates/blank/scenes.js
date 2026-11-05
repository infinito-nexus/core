film({ W: 1920, H: 1080, BPM: 120, BEATS: 24 });

const COPY = { title: "Make anything move.", kicker: "MOTION, FROM CODE", stat: 1440, statLabel: "frames, each one a function of time", type: "Every frame is a function of t.", glitch: "GLITCH", fx: "grain, glitch, confetti" };
const CHART = [0.12, 0.2, 0.18, 0.34, 0.31, 0.5, 0.47, 0.66, 0.72, 0.9];
const SHOTS = [];

const titleShot = (id) => `
  <div class="shot" data-k="${id}">
    <div class="abs mask" style="left:200px;top:330px;width:1200px;height:40px"><div data-k="${id}Kick" class="t kicker">${COPY.kicker}</div></div>
    <div class="abs mask" style="left:200px;top:380px;width:1600px;height:180px">
      <div data-k="${id}Title" class="t h1">${COPY.title}</div>
    </div>
    <div class="abs" data-k="${id}Rule" style="left:204px;top:600px;width:420px;height:6px;border-radius:3px;background:var(--accent);transform-origin:0 50%"></div>
  </div>`;

function build(stage) {
  const pts = CHART.map((v, i) => `${(i * 1100) / (CHART.length - 1)},${(380 - v * 340).toFixed(1)}`).join(" L");
  stage.innerHTML = `
    <div class="full" data-k="world">
      ${titleShot("s1")}
      <div class="shot" data-k="s2">
        <div class="abs" style="left:160px;top:300px"><div data-k="stat" class="t" style="font-size:180px;font-weight:800;letter-spacing:-0.04em;font-variant-numeric:tabular-nums;color:var(--accent)">0</div></div>
        <div class="abs mask" style="left:166px;top:520px;width:640px;height:46px"><div data-k="statLabel" class="t" style="font-size:32px;font-weight:500;color:var(--ink2)">${COPY.statLabel}</div></div>
        <svg class="abs" style="left:700px;top:280px;overflow:visible" width="1100" height="400" viewBox="0 0 1100 400">
          <path d="M0 380 L1100 380" stroke="var(--hair)" stroke-width="2"/>
          <path data-k="line" d="M${pts}" fill="none" stroke="var(--accent2)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="shot center" data-k="s3" style="flex-direction:column;gap:30px">
        <div data-k="glitchWord" class="t" style="font-size:220px;font-weight:900;letter-spacing:-0.03em">${COPY.glitch}</div>
        <div class="mask" style="height:46px"><div data-k="fxLine" class="t" style="font-size:34px;font-weight:500;color:var(--ink2)">${COPY.fx}</div></div>
        <div class="full" data-k="confetti" style="pointer-events:none"></div>
      </div>
      <div class="shot" data-k="s4" style="background:var(--bg2)">
        <div class="abs row" style="left:200px;top:470px;height:110px"><span data-k="typed" class="t" style="font-family:var(--mono);font-size:84px;font-weight:600"></span>
          <span data-k="caret" style="width:8px;height:96px;margin-left:10px;background:var(--accent)"></span></div>
        <div class="abs mask" style="left:204px;top:620px;width:900px;height:44px"><div data-k="scram" class="t" style="font-family:var(--mono);font-size:30px;color:var(--ink3)"></div></div>
      </div>
      ${titleShot("s5")}
    </div>
    ${vignetteLayer(0.5)}
    ${grainLayer(0.14)}`;
  collect(stage);
  split($.s1Title, "word", true);
  $.s5Words = split($.s5Title, "word", true);
  SHOTS.push(
    { k: "s1", t0: 0 },
    { k: "s2", t0: B(5), join: ["push", 0.6, { dir: "left" }] },
    { k: "s3", t0: B(11), join: ["zoom", 0.5] },
    { k: "s4", t0: B(15), join: ["whip", 0.45, { dir: "left" }] },
    { k: "s5", t0: B(19), join: ["iris", 0.6, { x: "50%", y: "50%" }] },
  );
}

function apply(t) {
  sequence(t, SHOTS);
  grain(t);

  sweep($.s1Title, prog(t, B(2), 1.1, E.inOut), "#F2C14E");
  sweep($.s5Title, 0, "#F2C14E");
  setT($.s1Rule, `scaleX(${(1 - 0.35 * pulse(t, B(3), 0.6)).toFixed(4)})`);

  $.stat.textContent = countUp(t, B(6), 1.6, 0, COPY.stat);
  rise($.statLabel, prog(t, B(6) + 0.3, 0.5, E.out));
  drawPath($.line, prog(t, B(7), 1.8, E.inOut));

  glitch($.glitchWord, t, B(12), 0.35, 16);
  rise($.fxLine, prog(t, B(12) + 0.2, 0.5, E.out));
  confetti($.confetti, t, B(13), { x: FILM.W / 2, y: FILM.H / 2 + 40 });
  const hit = shake(t, B(13), 0.45, 14);
  moveCamera($.world, hit);

  $.typed.textContent = typewriter(COPY.type, t, B(15) + 0.4, 22);
  show($.caret, t < B(15) + 0.4 || t > B(15) + 0.4 + COPY.type.length / 22 ? caret(t) : true);
  $.scram.textContent = scramble("seek(t) renders the same picture, every time", t, B(17), 0.9, 4);

  $.s5Words.forEach((w, i) => rise(w, stagger(t, B(19) + 0.15, i, 0.08, 0.55, E.out)));
  rise($.s5Kick, prog(t, B(19) + 0.1, 0.5, E.out));
  setT($.s5Rule, `scaleX(${prog(t, B(19) + 0.6, 0.6, E.out).toFixed(4)})`);
}
