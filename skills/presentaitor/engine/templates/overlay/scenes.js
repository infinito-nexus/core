film({ W: 1920, H: 1080, BPM: 120, BEATS: 16 });

const LOWER = { name: "Alex Rivera", role: "Founder, Example Co." };
const WORDS = [["Graphics", 1.2], ["drawn", 1.55], ["over", 1.85], ["your", 2.05], ["footage,", 2.3], ["frame", 3.0], ["by", 3.3], ["frame.", 3.5]];
const LINE_END = 5.6;

function build(stage) {
  stage.innerHTML = `
    <div class="abs" style="left:120px;top:780px">
      <div class="abs" data-k="bar" style="left:0;top:0;width:10px;height:132px;border-radius:5px;background:var(--accent)"></div>
      <div class="abs mask" style="left:34px;top:0;width:900px;height:84px"><div data-k="name" class="t" style="font-size:64px;font-weight:800;letter-spacing:-0.02em">${LOWER.name}</div></div>
      <div class="abs mask" style="left:36px;top:84px;width:900px;height:48px"><div data-k="role" class="t" style="font-size:34px;font-weight:500;color:var(--ink2)">${LOWER.role}</div></div>
    </div>
    <div class="abs center" style="left:0;right:0;top:930px">
      <div class="pill t" data-k="cap" style="font-size:46px;font-weight:700">${WORDS.map(([w], i) => `<span data-k="w${i}">${w}</span>`).join(" ")}</div>
    </div>`;
  collect(stage);
}

function apply(t) {
  const lin = prog(t, B(2), 0.45, E.out), lout = prog(t, B(13), 0.4, E.in);
  setT($.bar, `scaleY(${(lin * (1 - lout)).toFixed(4)})`);
  $.bar.style.transformOrigin = "50% 100%";
  setT($.name, TRAVEL(t < B(13) ? 1 - prog(t, B(2) + 0.15, 0.5, E.out) : prog(t, B(13), 0.35, E.in)));
  setT($.role, TRAVEL(t < B(13) ? 1 - prog(t, B(2) + 0.3, 0.5, E.out) : prog(t, B(13) + 0.05, 0.35, E.in)));

  const on = t >= WORDS[0][1] - 0.2 && t < LINE_END;
  show($.cap, on);
  $.cap.style.opacity = (prog(t, WORDS[0][1] - 0.2, 0.2, E.out) * (1 - prog(t, LINE_END - 0.2, 0.2, E.in))).toFixed(3);
  WORDS.forEach(([, at], i) => {
    const next = WORDS[i + 1] ? WORDS[i + 1][1] : LINE_END;
    $["w" + i].style.color = t >= at && t < next ? "var(--accent)" : t >= at ? "var(--ink)" : "var(--ink3)";
  });
}
