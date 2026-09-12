"""Render the bond matrix as an HTML page, optionally editable.

Every cell carries both directions of one pair, row-to-column above
column-to-row, because a bond is declared on the consumer's side and the two
need not agree. Brightness is the bond: black for none, white for 1.
"""

from __future__ import annotations

import html
import json
from typing import Any

_STYLE = """
:root { color-scheme: dark; --bg:#0b0c0e; --fg:#d8d8d8; --grid:#ffffff1c; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:12px/1.35 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
header { position:sticky; top:0; z-index:5; background:var(--bg);
         border-bottom:1px solid var(--grid); padding:10px 14px; }
h1 { margin:0 0 4px; font-size:15px; font-weight:600; }
.meta { opacity:.65; }
.legend { margin-top:7px; display:flex; gap:14px; flex-wrap:wrap; align-items:center; }
.ramp { display:inline-block; width:120px; height:11px; border:1px solid var(--grid);
        background:linear-gradient(to right,#000,#fff); vertical-align:-2px; margin:0 5px; }
#q { margin-top:8px; padding:4px 7px; width:260px; border:1px solid var(--grid);
     border-radius:4px; background:transparent; color:inherit; font:inherit; }
#msg { margin-left:10px; font-size:11px; opacity:0; transition:opacity .15s; }
#msg.on { opacity:1; } #msg.bad { color:#f77; }
.wrap { overflow:auto; max-height:calc(100vh - 130px); }
table { border-collapse:separate; border-spacing:0; }
th, td { border-right:1px solid var(--grid); border-bottom:1px solid var(--grid); }
thead th { position:sticky; top:0; z-index:3; background:var(--bg); height:132px;
           vertical-align:bottom; padding:0; }
thead th div { writing-mode:vertical-rl; transform:rotate(180deg);
               padding:6px 3px; white-space:nowrap; font-weight:500; }
tbody th { position:sticky; left:0; z-index:2; background:var(--bg); text-align:left;
           padding:0 8px 0 6px; white-space:nowrap; font-weight:500; }
thead th:first-child { position:sticky; left:0; z-index:4; background:var(--bg); }
td { width:30px; min-width:30px; padding:0; }
.b, .nb { display:block; height:13px; text-align:center; font-size:9px; line-height:13px;
          font-variant-numeric:tabular-nums; }
.nb { background:#000; }
.b[data-c] { cursor:pointer; }
.b[data-c]:hover { outline:1px solid #4af; outline-offset:-1px; }
.diag { background:repeating-linear-gradient(45deg,#000,#000 3px,#1b1d22 3px,#1b1d22 6px); }
#ed { position:fixed; z-index:9; width:44px; height:22px; padding:0 3px; text-align:center;
      border:1px solid #4af; border-radius:3px; background:#000; color:#fff;
      font:11px ui-monospace,monospace; display:none; }
.hidden { display:none; }
"""

_SCRIPT = """
const box = document.getElementById('q');
const rows = [...document.querySelectorAll('tbody tr')];
const heads = [...document.querySelectorAll('thead th[data-role]')];
box.addEventListener('input', () => {
  const q = box.value.trim().toLowerCase();
  rows.forEach(tr => tr.classList.toggle('hidden', !!q && !tr.dataset.role.includes(q)));
  heads.forEach((th, i) => {
    const hit = !q || th.dataset.role.includes(q) ||
      rows.some(tr => !tr.classList.contains('hidden') &&
                      tr.children[i + 1].dataset.filled === '1');
    th.classList.toggle('hidden', !hit);
    rows.forEach(tr => tr.children[i + 1].classList.toggle('hidden', !hit));
  });
});

const ed = document.getElementById('ed');
const msg = document.getElementById('msg');
let cur = null;

function say(text, bad) {
  msg.textContent = text;
  msg.className = 'on' + (bad ? ' bad' : '');
  setTimeout(() => { msg.className = ''; }, 2600);
}

function close() { ed.style.display = 'none'; cur = null; }

document.querySelector('tbody').addEventListener('click', e => {
  const bar = e.target.closest('.b[data-c]');
  if (!bar) { close(); return; }
  cur = bar;
  const r = bar.getBoundingClientRect();
  ed.style.left = Math.round(r.left + r.width / 2 - 22) + 'px';
  ed.style.top = Math.round(r.top + r.height / 2 - 11) + 'px';
  ed.style.display = 'block';
  ed.value = bar.dataset.b || '';
  ed.select();
});

ed.addEventListener('keydown', e => {
  if (e.key === 'Escape') { close(); return; }
  if (e.key !== 'Enter') return;
  const bar = cur, value = ed.value;
  close();
  fetch('bond', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ consumer: bar.dataset.c, provider: bar.dataset.p, value })
  }).then(r => r.json()).then(d => {
    if (!d.ok) { say(d.error, true); return; }
    bar.textContent = d.text;
    bar.dataset.b = d.text;
    bar.style.background = d.bg;
    bar.style.color = d.fg;
    say(d.written);
  }).catch(err => say(String(err), true));
});
ed.addEventListener('blur', close);
"""


def shade(bond: float) -> tuple[str, str]:
    """Return the (background, foreground) pair for a bond between 0 and 1."""
    level = round(max(0.0, min(1.0, bond)) * 255)
    return f"rgb({level},{level},{level})", "#000" if level > 140 else "#fff"


def _bar(
    edge: dict[str, Any] | None, consumer: str, provider: str, editable: bool
) -> str:
    """Return one of a cell's two direction bars."""
    if edge is None:
        return '<span class="nb"></span>'
    bond = edge["bond"]
    background, foreground = shade(bond)
    text = f"{bond:g}"
    handle = ""
    if editable:
        handle = (
            f' data-c="{html.escape(consumer)}" data-p="{html.escape(provider)}"'
            f' data-b="{text}"'
        )
    return (
        f'<span class="b" style="background:{background};color:{foreground}"{handle}'
        f' title="{html.escape(consumer)} &rarr; {html.escape(edge["service_key"])}">'
        f"{text}</span>"
    )


def render(
    edges: dict[tuple[str, str], dict[str, Any]],
    roles: list[str],
    *,
    editable: bool = False,
) -> str:
    """Return the full HTML page for the given edges.

    Args:
        edges: the collected ``{(consumer, provider): edge}`` mapping.
        roles: every participating role, in the order rows and columns take.
        editable: wire the cells to the server's write endpoint.
    """
    head = "".join(
        f'<th data-role="{html.escape(r.lower())}"><div>{html.escape(r)}</div></th>'
        for r in roles
    )
    body = []
    for row in roles:
        cells = []
        for col in roles:
            if row == col:
                cells.append('<td class="diag" data-filled="0"></td>')
                continue
            out, back = edges.get((row, col)), edges.get((col, row))
            filled = "1" if out is not None or back is not None else "0"
            cells.append(
                f'<td data-filled="{filled}">'
                + _bar(out, row, col, editable)
                + _bar(back, col, row, editable)
                + "</td>"
            )
        body.append(
            f'<tr data-role="{html.escape(row.lower())}">'
            f"<th>{html.escape(row)}</th>" + "".join(cells) + "</tr>"
        )

    hint = (
        "click a bar to edit, Enter writes it to the role"
        if editable
        else "read only, run without --out to edit"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bond matrix</title><style>{_STYLE}</style></head>
<body>
<header>
  <h1>Bond matrix</h1>
  <div class="meta">{len(edges)} bonds across {len(roles)} roles &middot;
    row &rarr; column above column &rarr; row &middot; {hint}</div>
  <div class="legend">
    <span>0<span class="ramp"></span>1</span>
    <span><span class="ramp" style="width:13px;background:#000"></span>no bond</span>
  </div>
  <input id="q" type="search" placeholder="filter roles" autocomplete="off"><span id="msg"></span>
</header>
<div class="wrap"><table>
<thead><tr><th></th>{head}</tr></thead>
<tbody>{"".join(body)}</tbody>
</table></div>
<input id="ed" inputmode="decimal" autocomplete="off">
<script>{_SCRIPT}</script>
</body></html>
"""


def render_json(edges: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Return the same data as JSON, for a caller that wants to post-process."""
    return json.dumps(
        [
            {"consumer": consumer, "provider": provider, **edge}
            for (consumer, provider), edge in sorted(edges.items())
        ],
        indent=2,
    )
