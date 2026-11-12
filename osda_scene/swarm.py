# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-cursor swarm：沿轮廓绘制的构建回放。

和"淡入 + 光标乱飞"的区别：
- 每个元素用 stroke-dashoffset 逐段显形，光标用 getPointAtLength() 贴着轮廓走；
- 多个光标分头同时画各自负责的元素，不是排队一个一个来；
- 文字/位图/外部面板没有轮廓，退化为原地淡入，光标直线移动到其位置。

输出单文件 HTML，可暂停/重播，不依赖任何库。
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

PALETTE = [
    "#E4572E", "#17BEBB", "#FFC914", "#76B041", "#3F88C5", "#9467BD",
    "#D81159", "#8F2D56", "#2A9D8F", "#F4A261", "#4361EE", "#7B2CBF",
]

CURSOR_SHAPE = "M0,0 L0,13 L3.6,9.6 L6.2,15 L8.4,13.8 L5.9,8.6 L10.5,7.2 Z"
SHAPE_TYPES = {"rect", "circle", "line", "arrow", "path"}


def _anchor(el: dict[str, Any], fallback: tuple[float, float]) -> tuple[float, float]:
    kind = el["type"]
    if kind == "rect":
        return el["x_mm"] + el["w_mm"] / 2, el["y_mm"] + el["h_mm"] / 2
    if kind == "circle":
        return el["cx_mm"], el["cy_mm"]
    if kind in ("line", "arrow"):
        return (el["x1_mm"] + el["x2_mm"]) / 2, (el["y1_mm"] + el["y2_mm"]) / 2
    if kind == "text":
        return el["x_mm"], el["y_mm"] - 1.0
    if kind in ("image", "panel"):
        width = float(el.get("w_mm", 20))
        height = float(el.get("h_mm", width * 0.75))
        return el["x_mm"] + width / 2, el["y_mm"] + height / 2
    return fallback


def build_swarm_html(svg_path: str | Path, spec: dict[str, Any],
                     elements: list[dict[str, Any]],
                     out_html: str | Path) -> dict:
    cfg = spec["swarm"]
    duration = float(cfg["duration_s"])
    mode = cfg.get("mode", "spatial")
    trail = max(0, min(60, int(cfg.get("trail", 20))))
    presentation_only = bool(cfg.get("presentation_only", True))
    width = spec["canvas"]["width_mm"]
    height = spec["canvas"]["height_mm"]
    center = (width / 2, height / 2)

    ordered = list(elements)
    if mode == "spatial":
        ordered = sorted(elements, key=lambda el: (_anchor(el, center)[1],
                                                   _anchor(el, center)[0]))

    requested = max(2, min(30, int(cfg["cursors"])))
    count = max(2, min(requested, len(ordered)))

    # 按光标分车道：spatial 为连续切片（各画一片区域），follow 为轮转（按绘制顺序交替）
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(count)]
    if mode == "spatial":
        chunk = max(1, -(-len(ordered) // count))
        for i, el in enumerate(ordered):
            lanes[min(i // chunk, count - 1)].append(el)
    else:
        for i, el in enumerate(ordered):
            lanes[i % count].append(el)

    per = max(0.15, duration / max(len(lane) for lane in lanes))
    fade_dur = 0.5
    total = round(per * max(len(lane) for lane in lanes) + fade_dur, 2)

    kinds = {el["id"]: ("shape" if el["type"] in SHAPE_TYPES else "fade")
             for el in ordered}
    anchors = {el["id"]: [round(v, 2) for v in _anchor(el, center)] for el in ordered}
    labels = {el["id"]: _label_of(el) for el in ordered}

    svg_text = Path(svg_path).read_text(encoding="utf-8")
    if svg_text.startswith("<?xml"):
        svg_text = svg_text.split("?>", 1)[1].lstrip()

    starts = [((i + 0.5) * width / count, -5.0) for i in range(count)]
    cursor_svg, trail_svg, label_svg = [], [], []
    for i in range(count):
        color = PALETTE[i % len(PALETTE)]
        cursor_svg.append(
            f'<g class="cursor" id="cur{i}" opacity="0" '
            f'transform="translate({starts[i][0]:.2f},{starts[i][1]:.2f})">'
            f'<path d="{CURSOR_SHAPE}" fill="{color}" stroke="#ffffff" '
            f'stroke-width="1.4" transform="scale(0.14)"/></g>')
        trail_svg.append(
            f'<polyline id="trail{i}" fill="none" stroke="{color}" stroke-width="0.35" '
            f'stroke-opacity="0.4" stroke-dasharray="0.4 0.7" points=""/>')
        label_svg.append(
            f'<text id="lab{i}" font-family="Arial" font-size="1.4" fill="{color}" '
            f'opacity="0">DRAW {i + 1}</text>')

    payload_lanes = [[el["id"] for el in lane] for lane in lanes]
    title = html.escape(spec.get("name", "figure"))
    presentation_css = ("  .bar, .note { display: none; }\n"
                        if presentation_only else "")
    doc = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{title} — build replay</title>
<style>
  body {{ margin: 0; background: #f4f4f1; font-family: Arial, sans-serif; color: #222; }}
  .wrap {{ max-width: 1100px; margin: 20px auto; padding: 0 16px; }}
  .bar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; }}
  button {{ font: inherit; padding: 4px 12px; border: 1px solid #bbb; background: #fff;
            border-radius: 4px; cursor: pointer; }}
  button:hover {{ background: #eee; }}
  .track {{ flex: 1; height: 4px; background: #ddd; border-radius: 2px; overflow: hidden; }}
  .fill {{ height: 100%; width: 0; background: #3F88C5; }}
  .stage {{ position: relative; background: #fff; border: 1px solid #ddd; }}
  .stage > svg {{ width: 100%; height: auto; display: block; }}
  .overlay {{ position: absolute; inset: 0; pointer-events: none; }}
  .overlay svg {{ width: 100%; height: 100%; display: block; }}
  [id^="el_"] {{ opacity: 0; }}
  .note {{ color: #666; font-size: 12px; margin-top: 8px; line-height: 1.6; }}
{presentation_css}</style>
<noscript><style>[id^="el_"] {{ opacity: 1 !important; }}</style></noscript>
</head>
<body>
<div class="wrap">
  <div class="bar">
    <button id="toggle">暂停</button>
    <button id="restart">重播</button>
    <span id="status">准备中…</span>
    <span class="track"><span class="fill" id="progress"></span></span>
  </div>
  <div class="stage">
    {svg_text}
    <div class="overlay">
      <svg id="ov" viewBox="0 0 {width:g} {height:g}" xmlns="http://www.w3.org/2000/svg">
        {''.join(trail_svg)}
        {''.join(cursor_svg)}
        {''.join(label_svg)}
      </svg>
    </div>
  </div>
  <p class="note">构建回放：每个元素按轮廓逐段画出，光标贴着轮廓走；
  {count} 个光标分头同时绘制，共 {len(ordered)} 个元素、约 {total:g} 秒一轮；
  绘制结束后光标原地淡出并清除尾迹。仅用于演示绘制过程，不影响静态图。</p>
</div>
<script>
const lanes = {json.dumps(payload_lanes, ensure_ascii=False)};
const kinds = {json.dumps(kinds, ensure_ascii=False)};
const anchors = {json.dumps(anchors, ensure_ascii=False)};
const labels = {json.dumps(labels, ensure_ascii=False)};
const per = {per:.4f};
const fadeDur = {fade_dur:.2f};
const total = {total:.4f};
const trailLen = {trail};
const drawEnd = Math.max(...lanes.map(l => l.length)) * per;
const count = {count};
const overlay = document.getElementById("ov");

const state = {{ t: 0, playing: true, last: 0 }};
const toggle = document.getElementById("toggle");
const statusEl = document.getElementById("status");
const fillEl = document.getElementById("progress");
const shapes = {{}};
const prepared = new Set();
const trails = Array.from({{ length: count }}, () => []);
const active = Array.from({{ length: count }}, () => null);

function groupOf(id) {{ return document.getElementById("el_" + id); }}

function prepare(id) {{
  if (prepared.has(id)) return;
  prepared.add(id);
  const g = groupOf(id);
  if (!g) return;
  if (kinds[id] !== "shape") return;
  const shape = g.querySelector("rect,circle,ellipse,line,path,polygon,polyline");
  if (!shape) return;
  let len = 0;
  try {{ len = shape.getTotalLength(); }} catch (e) {{ len = 0; }}
  const stroke = shape.getAttribute("stroke");
  if (!len || stroke === "none" || stroke === null) return;
  shape.style.strokeDasharray = len;
  shape.style.strokeDashoffset = len;
  if (shape.getAttribute("fill") && shape.getAttribute("fill") !== "none") {{
    shape.style.fillOpacity = "0";
  }}
  const head = g.querySelector(".arrowhead");
  if (head) head.style.opacity = "0";   // 箭头等线条画完再出现
  shapes[id] = {{ el: shape, len: len, head: head }};
}}

function toOverlay(shape, pt) {{
  const p = overlay.createSVGPoint();
  p.x = pt.x; p.y = pt.y;
  const m = shape.getScreenCTM();
  if (!m) return null;
  const q = p.matrixTransform(m).matrixTransform(overlay.getScreenCTM().inverse());
  return [q.x, q.y];
}}

function placeCursor(i, x, y) {{
  const g = document.getElementById("cur" + i);
  const lab = document.getElementById("lab" + i);
  if (!g) return;
  g.setAttribute("transform", `translate(${{x}},${{y}})`);
  g.setAttribute("opacity", "1");
  if (lab) {{ lab.setAttribute("x", x + 2.2); lab.setAttribute("y", y + 1.0);
             lab.setAttribute("opacity", "1"); }}
}}

function hideCursor(i) {{
  const g = document.getElementById("cur" + i);
  const lab = document.getElementById("lab" + i);
  if (g) g.setAttribute("opacity", "0");
  if (lab) lab.setAttribute("opacity", "0");
}}

function setOpacity(i, value) {{
  const g = document.getElementById("cur" + i);
  const lab = document.getElementById("lab" + i);
  if (g) g.setAttribute("opacity", String(Math.max(0, value)));
  if (lab) lab.setAttribute("opacity", String(Math.max(0, value)));
}}

function setCursor(i, x, y) {{
  placeCursor(i, x, y);
  const tr = trails[i];
  const last = tr[tr.length - 1];
  if (!last || Math.hypot(last[0] - x, last[1] - y) > 0.2) {{
    tr.push([x, y]);
    while (tr.length > trailLen) tr.shift();   // trail=0 时不留尾迹
    const poly = document.getElementById("trail" + i);
    if (poly) poly.setAttribute("points", tr.map(p => p.join(",")).join(" "));
  }}
}}

function clearTrail(i) {{
  trails[i] = [];
  const poly = document.getElementById("trail" + i);
  if (poly) poly.setAttribute("points", "");
}}

function drawShape(id, frac) {{
  const s = shapes[id];
  if (!s) return null;
  s.el.style.strokeDashoffset = s.len * (1 - frac);
  if (s.el.style.fillOpacity !== "") {{
    s.el.style.fillOpacity = frac > 0.92 ? "1" : "0";
  }}
  if (s.head) s.head.style.opacity = frac > 0.97 ? "1" : "0";
  try {{ return toOverlay(s.el, s.el.getPointAtLength(s.len * frac)); }}
  catch (e) {{ return null; }}
}}

let doneCount = 0;
function render() {{
  doneCount = 0;
  for (let c = 0; c < count; c++) {{
    const lane = lanes[c];
    const idx = Math.floor(state.t / per);
    const frac = Math.min(1, (state.t - idx * per) / per);
    const nextId = idx < lane.length ? lane[idx] : null;
    if (nextId !== active[c]) {{ active[c] = nextId; clearTrail(c); }}
    if (idx >= lane.length) {{
      doneCount += lane.length;
      clearTrail(c);
      // 画完原地淡出，不移动
      const u = Math.min(1, (state.t - lane.length * per) / fadeDur);
      setOpacity(c, 1 - u);
      continue;
    }}
    const id = lane[idx];
    const g = groupOf(id);
    const anchor = anchors[id];

    prepare(id);
    const hasOutline = kinds[id] === "shape" && !!shapes[id];
    if (hasOutline) {{
      if (g) g.style.opacity = "1";
      const p = drawShape(id, frac);
      if (p) setCursor(c, p[0], p[1]);
      else setCursor(c, anchor[0], anchor[1]);
    }} else {{
      // 文字/位图/外部面板没有轮廓：原地淡入，光标直接出现在该位置
      if (g) g.style.opacity = String(Math.min(1, frac * 1.4));
      setCursor(c, anchor[0], anchor[1]);
    }}

    for (let i = 0; i < idx; i++) {{
      const gid = lane[i];
      const gg = groupOf(gid);
      if (gg) gg.style.opacity = "1";
      const s = shapes[gid];
      if (s) {{ s.el.style.strokeDashoffset = 0;
                if (s.el.style.fillOpacity !== "") s.el.style.fillOpacity = "1";
                if (s.head) s.head.style.opacity = "1"; }}
    }}
    doneCount += idx;
  }}
  // 全部结束后强制清场：光标、标签、尾迹都不许留在作图区
  if (state.t >= drawEnd + fadeDur - 0.001) {{
    for (let c = 0; c < count; c++) {{ hideCursor(c); clearTrail(c); }}
  }}
  const elapsed = Math.min(1, state.t / total);
  fillEl.style.width = (elapsed * 100).toFixed(1) + "%";
  statusEl.textContent = state.t >= total
    ? `绘制完成 · {len(ordered)} 个元素 · 光标已淡出`
    : `已画 ${{doneCount}}/{len(ordered)} 个元素 · ${{Math.round(elapsed * 100)}}%`;
}}

function frame(ts) {{
  if (!state.playing) {{ state.last = ts; requestAnimationFrame(frame); return; }}
  if (!state.last) state.last = ts;
  state.t += (ts - state.last) / 1000;
  state.last = ts;
  if (state.t >= total) {{ state.t = total; state.playing = false; toggle.textContent = "重播"; }}
  render();
  requestAnimationFrame(frame);
}}

toggle.onclick = () => {{
  if (state.t >= total) {{ location.reload(); return; }}
  state.playing = !state.playing;
  toggle.textContent = state.playing ? "暂停" : "继续";
  state.last = 0;
  render();
}};
document.getElementById("restart").onclick = () => location.reload();

render();
requestAnimationFrame(frame);
</script>
</body>
</html>
"""
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return {"html": str(out), "cursors": count, "steps": len(ordered),
            "duration_s": total, "mode": mode}


def _label_of(el: dict[str, Any]) -> str:
    if el["type"] == "text":
        if el.get("runs"):
            return "".join(str(r.get("t", "")) for r in el["runs"])[:24]
        return str(el.get("content", ""))[:24]
    return el["id"]
