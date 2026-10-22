// Charts drawn directly as SVG: no chart library to download, and every change glides
// (values morph, ranges zoom) instead of redrawing with a jump. They only draw what the
// page gives them; every figure was calculated in Python.

const NS = "http://www.w3.org/2000/svg";
export const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

// Colours given as "var(--brand)" are applied as styles, so a chart follows the company's
// colour even if the logo (which sets it) finishes loading after the chart is drawn.
const PAINT = new Set(["fill", "stroke", "stop-color"]);
export function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) {
    const v = attrs[k];
    if (PAINT.has(k) && typeof v === "string" && v.startsWith("var(")) n.style.setProperty(k, v);
    else n.setAttribute(k, v);
  }
  if (parent) parent.appendChild(n);
  return n;
}

const easeOut = t => 1 - Math.pow(1 - t, 3);

// Runs fn(progress 0..1) every frame. Returns a cancel function, so a new animation can
// take over from wherever the old one is (nothing waits for an animation to finish).
export function tween(ms, fn, done) {
  // No animation when motion is reduced, or when the page isn't visible (browsers pause
  // animation frames there, which would leave numbers frozen half-way).
  if (reduceMotion || ms <= 0 || document.hidden) { fn(1); done && done(); return () => {}; }
  let alive = true, finished = false; const t0 = performance.now();
  const finish = () => { if (!alive || finished) return; finished = true; fn(1); done && done(); };
  // The first frame's time can be a hair before t0; clamp so progress never goes below 0.
  const step = t => { if (!alive || finished) return; const p = Math.max(0, Math.min(1, (t - t0) / ms));
    if (p >= 1) return finish(); fn(easeOut(p)); requestAnimationFrame(step); };
  requestAnimationFrame(step);
  // If the browser stops sending frames (a background tab), still land on the final state.
  const timer = setTimeout(finish, ms + 200);
  return () => { alive = false; clearTimeout(timer); };
}

function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// Redraw a chart when its box changes size (window resize, panel shown), at most once a frame.
const watchers = new WeakMap();
const ro = new ResizeObserver(entries => {
  for (const e of entries) { const fn = watchers.get(e.target); if (fn) requestAnimationFrame(fn); }
});
function watch(host, fn) { watchers.set(host, fn); ro.observe(host); }

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || Math.abs(hi) || 1;
  const step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= count) || mag * 10;
  const start = Math.floor(lo / step) * step, ticks = [];
  // Ticks run from at or below the lowest value to at or above the highest, so nothing
  // drawn ever falls outside the axis.
  for (let v = start; v < hi + step * .999; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

function smoothPath(pts) {
  if (!pts.length) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], cx = (x0 + x1) / 2;
    d += ` C${cx.toFixed(1)} ${y0.toFixed(1)} ${cx.toFixed(1)} ${y1.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }
  return d;
}
const straightPath = pts => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");

function tipAt(tip, x, y, html) { tip.innerHTML = html; tip.style.left = x + "px"; tip.style.top = y + "px"; tip.style.opacity = 1; }

// ---------------------------------------------------------------------------
// Period chart: one value per quarter or year, as a smooth area line that morphs when
// the measure changes. Unusual changes are marked; clicking one calls onFlag.
// opts: { points: [{label, value, flag, note}], format, color, onFlag, tipText }
// ---------------------------------------------------------------------------
export function periodChart(host, tip) {
  const svg = el("svg", { role: "img" }, host);
  let opts = null, shown = null, cancel = () => {}, drawnOnce = false;

  function draw(values, progress = 1) {
    const r = host.getBoundingClientRect(), w = r.width, h = r.height;
    if (!w || !opts) return;
    const g = { l: 58, r: 16, t: 14, b: 30 };
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.textContent = "";
    const valid = values.filter(v => v != null);
    if (!valid.length) return;
    let lo = Math.min(...valid), hi = Math.max(...valid);
    if (opts.zeroBase && lo > 0) lo = 0;
    const pad = (hi - lo) * .15 || Math.abs(hi) * .1 || 1; lo -= lo === 0 ? 0 : pad; hi += pad;
    const ticks = niceTicks(lo, hi, 4); lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks.at(-1));
    const n = values.length, x = i => g.l + (n === 1 ? .5 : i / (n - 1)) * (w - g.l - g.r);
    const y = v => g.t + (1 - (v - lo) / (hi - lo)) * (h - g.t - g.b);
    const color = opts.color || "var(--brand)", faint = css("--faint"), line = css("--line");
    ticks.forEach(v => { el("line", { x1: g.l, x2: w - g.r, y1: y(v), y2: y(v), stroke: line }, svg);
      el("text", { x: g.l - 10, y: y(v) + 4, "text-anchor": "end", fill: faint, "font-size": 11 }, svg).textContent = opts.format(v); });
    if (lo < 0 && hi > 0) el("line", { x1: g.l, x2: w - g.r, y1: y(0), y2: y(0), stroke: css("--line-2") }, svg);
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((w - g.l) / 78))));
    opts.points.forEach((p, i) => { if ((n - 1 - i) % every === 0)
      el("text", { x: x(i), y: h - 8, "text-anchor": "middle", fill: faint, "font-size": 11 }, svg).textContent = p.short || p.label; });
    const defs = el("defs", {}, svg), gid = "g" + Math.random().toString(36).slice(2, 7);
    const gr = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: 0, "stop-color": color, "stop-opacity": .34 }, gr); el("stop", { offset: 1, "stop-color": color, "stop-opacity": 0 }, gr);
    // Lines break where a period is missing, rather than inventing a value.
    const segs = []; let cur = [];
    values.forEach((v, i) => { if (v == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push([x(i), y(v), i]); });
    if (cur.length) segs.push(cur);
    const base = y(Math.max(lo, Math.min(0, hi)));
    segs.forEach(s => {
      const d = s.length > 1 ? smoothPath(s) : "";
      if (s.length > 1) el("path", { d: `${d} L${s.at(-1)[0]} ${base} L${s[0][0]} ${base} Z`, fill: `url(#${gid})` }, svg);
      const ln = s.length > 1 ? el("path", { d, fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linecap": "round" }, svg) : null;
      if (ln && progress < 1) { const L = ln.getTotalLength(); ln.style.strokeDasharray = L; ln.style.strokeDashoffset = L * (1 - progress); }
      if (s.length === 1) el("circle", { cx: s[0][0], cy: s[0][1], r: 3.5, fill: color }, svg);
    });
    const lastI = values.map((v, i) => v == null ? -1 : i).filter(i => i >= 0).at(-1);
    if (lastI != null && progress >= 1) { el("circle", { cx: x(lastI), cy: y(values[lastI]), r: 9, fill: color, "fill-opacity": .22 }, svg);
      el("circle", { cx: x(lastI), cy: y(values[lastI]), r: 4.5, fill: color }, svg); }
    opts.points.forEach((p, i) => { if (!p.flag || values[i] == null || progress < 1) return;
      const c = el("circle", { cx: x(i), cy: y(values[i]), r: 6.5, fill: css("--flag"), stroke: css("--panel"), "stroke-width": 2, tabindex: 0, role: "button", "aria-label": `Unusual change in ${p.label}. Explain it.`, style: "cursor:pointer" }, svg);
      const go = () => opts.onFlag && opts.onFlag(p); c.addEventListener("click", go); c.addEventListener("keydown", e => { if (e.key === "Enter") go(); }); });
    const cross = el("line", { y1: g.t, y2: h - g.b, stroke: css("--line-2"), "stroke-dasharray": "3 4", opacity: 0, "pointer-events": "none" }, svg);
    const dot = el("circle", { r: 5, fill: css("--fg"), opacity: 0, "pointer-events": "none" }, svg);
    svg.onpointermove = e => { const rr = svg.getBoundingClientRect(); let i = Math.round((e.clientX - rr.left - g.l) / (w - g.l - g.r) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i)); if (values[i] == null) return;
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(values[i])); dot.setAttribute("opacity", 1);
      tipAt(tip, x(i), y(values[i]), opts.tipText(opts.points[i])); };
    svg.onpointerleave = () => { cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); tip.style.opacity = 0; };
  }

  watch(host, () => opts && draw(shown || opts.points.map(p => p.value)));

  return {
    set(next) {
      const target = next.points.map(p => p.value);
      const from = shown, sameShape = from && from.length === target.length && from.every((v, i) => (v == null) === (target[i] == null));
      opts = next; cancel();
      if (!drawnOnce || !sameShape) {          // first draw, or a different set of periods: draw the line in
        drawnOnce = true; shown = target;
        cancel = tween(900, p => draw(target, p));
        return;
      }
      // Same periods, new measure: glide each point from where it is now to where it goes,
      // in each series' own scale (so a $ series and a % series morph into each other).
      const norm = a => { const v = a.filter(x => x != null), lo = Math.min(...v), hi = Math.max(...v); return a.map(x => x == null ? null : (x - lo) / (hi - lo || 1)); };
      const a = norm(from), b = norm(target), v = target.filter(x => x != null), lo = Math.min(...v), hi = Math.max(...v);
      cancel = tween(620, p => { shown = a.map((s, i) => s == null ? null : lo + (s + (b[i] - s) * p) * (hi - lo)); draw(p < 1 ? shown : target); },
        () => { shown = target; });
    },
  };
}

// ---------------------------------------------------------------------------
// Time chart for prices: daily points, event markers, a range that zooms smoothly.
// opts: { points: [[ms, value]], events: [{ms, title, severity, id}], onEvent, format }
// ---------------------------------------------------------------------------
export function timeChart(host, tip) {
  const svg = el("svg", { role: "img" }, host);
  let opts = null, domain = null, cancel = () => {};

  function draw(progress = 1) {
    const r = host.getBoundingClientRect(), w = r.width, h = r.height;
    if (!w || !opts || !domain) return;
    const g = { l: 58, r: 16, t: 16, b: 30 }; svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.textContent = "";
    const [t0, t1] = domain, inView = opts.points.filter(p => p[0] >= t0 && p[0] <= t1);
    if (inView.length < 2) return;
    const vals = inView.map(p => p[1]); let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * .12 || 1; lo -= pad; hi += pad;
    const ticks = niceTicks(lo, hi, 4).filter(v => v >= lo && v <= hi);
    const x = t => g.l + (t - t0) / (t1 - t0) * (w - g.l - g.r), y = v => g.t + (1 - (v - lo) / (hi - lo)) * (h - g.t - g.b);
    const color = "var(--brand)", faint = css("--faint");
    ticks.forEach(v => { el("line", { x1: g.l, x2: w - g.r, y1: y(v), y2: y(v), stroke: css("--line") }, svg);
      el("text", { x: g.l - 10, y: y(v) + 4, "text-anchor": "end", fill: faint, "font-size": 11 }, svg).textContent = opts.format(v); });
    const spanDays = (t1 - t0) / 864e5, months = Math.max(1, Math.round(spanDays / 30 / Math.max(2, Math.floor((w - g.l) / 90))));
    const d = new Date(t0); d.setDate(1); d.setMonth(d.getMonth() + 1);
    for (; d.getTime() <= t1; d.setMonth(d.getMonth() + months)) {
      const label = spanDays > 800 ? (d.getMonth() === 0 ? String(d.getFullYear()) : null)
        : d.toLocaleString("en-US", { month: "short" }) + (d.getMonth() === 0 ? " '" + String(d.getFullYear()).slice(2) : "");
      if (label) el("text", { x: x(d.getTime()), y: h - 8, "text-anchor": "middle", fill: faint, "font-size": 11 }, svg).textContent = label;
    }
    const step = Math.max(1, Math.floor(inView.length / (w - g.l - g.r)));      // at most one point per pixel
    const pts = inView.filter((_, i) => i % step === 0 || i === inView.length - 1).map(p => [x(p[0]), y(p[1])]);
    const defs = el("defs", {}, svg), gr = el("linearGradient", { id: "pg", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: 0, "stop-color": color, "stop-opacity": .3 }, gr); el("stop", { offset: 1, "stop-color": color, "stop-opacity": 0 }, gr);
    const line = straightPath(pts), base = h - g.b;
    el("path", { d: `${line} L${pts.at(-1)[0]} ${base} L${pts[0][0]} ${base} Z`, fill: "url(#pg)", opacity: progress }, svg);
    const ln = el("path", { d: line, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    if (progress < 1) { const L = ln.getTotalLength(); ln.style.strokeDasharray = L; ln.style.strokeDashoffset = L * (1 - progress); }
    const valueAt = t => { let i = opts.points.findIndex(p => p[0] >= t); if (i <= 0) return opts.points[Math.max(0, i)][1]; const [ta, a] = opts.points[i - 1], [tb, b] = opts.points[i]; return a + (b - a) * (t - ta) / (tb - ta || 1); };
    if (progress >= 1) (opts.events || []).forEach(ev => { if (ev.ms < t0 || ev.ms > t1) return;
      const cx = x(ev.ms), cy = y(valueAt(ev.ms)), col = ev.kind === "move" ? css("--down") : css("--flag");
      el("circle", { cx, cy, r: 11, fill: col, "fill-opacity": .18, "pointer-events": "none" }, svg);
      const c = el("circle", { cx, cy, r: 6, fill: col, stroke: css("--panel"), "stroke-width": 2, tabindex: 0, role: "button", "aria-label": ev.title, style: "cursor:pointer" }, svg);
      const go = () => opts.onEvent && opts.onEvent(ev); c.addEventListener("click", go); c.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
      c.addEventListener("pointerenter", () => tipAt(tip, cx, cy, `${new Date(ev.ms).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}<b>${ev.title}</b>`)); });
    const cross = el("line", { y1: g.t, y2: base, stroke: css("--line-2"), "stroke-dasharray": "3 4", opacity: 0, "pointer-events": "none" }, svg);
    svg.onpointermove = e => { if (e.target.getAttribute("role") === "button") return; const rr = svg.getBoundingClientRect(), mx = e.clientX - rr.left;
      const t = t0 + (mx - g.l) / (w - g.l - g.r) * (t1 - t0); let best = inView[0]; for (const p of inView) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      cross.setAttribute("x1", x(best[0])); cross.setAttribute("x2", x(best[0])); cross.setAttribute("opacity", 1);
      tipAt(tip, x(best[0]), y(best[1]), `${new Date(best[0]).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}<b>${opts.format(best[1])}</b>`); };
    svg.onpointerleave = () => { cross.setAttribute("opacity", 0); tip.style.opacity = 0; };
  }
  watch(host, () => draw());
  return {
    set(next, from, to) {           // first call draws the line in
      opts = next; cancel(); domain = [from, to]; cancel = tween(1000, p => draw(p));
    },
    zoom(from, to) {                // later calls glide the visible range
      cancel(); const [a0, a1] = domain || [from, to];
      cancel = tween(650, p => { domain = [a0 + (from - a0) * p, a1 + (to - a1) * p]; draw(); });
    },
  };
}

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------
export function sparkline(svg, values, color, fill = false) {
  svg.textContent = "";
  const v = values.filter(x => x != null); if (v.length < 2) return;
  const vb = svg.viewBox.baseVal, W = vb && vb.width ? vb.width : 100, H = vb && vb.height ? vb.height : 34;
  const lo = Math.min(...v), hi = Math.max(...v), pts = [];
  values.forEach((x, i) => { if (x != null) pts.push([i / (values.length - 1) * W, H - 3 - (x - lo) / (hi - lo || 1) * (H - 6)]); });
  const d = straightPath(pts);
  if (fill) el("path", { d: `${d} L${W} ${H} L0 ${H} Z`, fill: color, "fill-opacity": .14 }, svg);
  const ln = el("path", { d, fill: "none", stroke: color, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }, svg);
  if (!reduceMotion) { ln.style.strokeDasharray = 600; ln.style.strokeDashoffset = 600; requestAnimationFrame(() => { ln.style.transition = "stroke-dashoffset 1.2s cubic-bezier(.22,1,.36,1)"; ln.style.strokeDashoffset = 0; }); }
}

export function ring(svg, pct, color, delay = 0) {
  svg.setAttribute("viewBox", "0 0 34 34"); svg.textContent = "";
  el("circle", { cx: 17, cy: 17, r: 13, fill: "none", stroke: css("--line"), "stroke-width": 4 }, svg);
  const c = el("circle", { cx: 17, cy: 17, r: 13, fill: "none", stroke: color, "stroke-width": 4, "stroke-linecap": "round", transform: "rotate(-90 17 17)" }, svg);
  const C = 2 * Math.PI * 13; c.style.strokeDasharray = C; c.style.strokeDashoffset = C;
  setTimeout(() => tween(1000, p => { c.style.strokeDashoffset = C * (1 - p * Math.max(0, Math.min(100, pct)) / 100); }), delay);
}

// Where the revenue went: ribbons from one bar into the parts.
// flow: { revenue, parts: [{name, value, key}] }   colors: { key: color }
export function sankey(host, flow, colors, format) {
  const svg = el("svg", { role: "img", "aria-label": "Where the revenue went" }, host);
  function draw(progress = 1) {
    const r = host.getBoundingClientRect(), w = r.width, h = r.height; if (!w) return;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.textContent = "";
    const narrow = w < 560, top = 16, H = h - 40, bw = 14, gap = 16;
    const x0 = narrow ? 70 : Math.max(120, w * .17), x1 = w - (narrow ? 120 : Math.max(190, w * .26));
    const fg = css("--fg"), muted = css("--muted");
    el("rect", { x: x0 - bw, y: top, width: bw, height: H, rx: 4, fill: "var(--brand)" }, svg);
    el("text", { x: x0 - bw - 10, y: top + H / 2 - 6, "text-anchor": "end", fill: fg, "font-size": 14, "font-family": "Sora" }, svg).textContent = "Revenue";
    el("text", { x: x0 - bw - 10, y: top + H / 2 + 14, "text-anchor": "end", fill: muted, "font-size": 13 }, svg).textContent = format(flow.revenue);
    const avail = H - gap * (flow.parts.length - 1); let ys = top, ye = top;
    flow.parts.forEach((p, i) => {
      const hs = p.value / flow.revenue * H, he = p.value / flow.revenue * avail, col = colors[p.key] || "#56637c";
      const grow = Math.min(1, Math.max(0, progress * 1.4 - i * .12));
      const xe = x0 + (x1 - x0) * grow, cm = x0 + (xe - x0) / 2;
      const d = `M${x0} ${ys} C${cm} ${ys} ${cm} ${ye} ${xe} ${ye} L${xe} ${ye + he} C${cm} ${ye + he} ${cm} ${ys + hs} ${x0} ${ys + hs} Z`;
      const rib = el("path", { d, fill: col, "fill-opacity": .3, style: "transition: fill-opacity .2s" }, svg);
      rib.addEventListener("pointerenter", () => rib.setAttribute("fill-opacity", .55)); rib.addEventListener("pointerleave", () => rib.setAttribute("fill-opacity", .3));
      if (grow >= 1) {
        el("rect", { x: x1, y: ye, width: bw, height: Math.max(3, he), rx: 4, fill: col }, svg);
        const ty = ye + he / 2;
        el("text", { x: x1 + bw + 12, y: ty - 3, fill: fg, "font-size": 14, "font-family": "Sora" }, svg).textContent = p.name;
        el("text", { x: x1 + bw + 12, y: ty + 15, fill: muted, "font-size": 13 }, svg).textContent = `${format(p.value)} · ${Math.round(p.value / flow.revenue * 100)}¢ per $1`;
      }
      ys += hs; ye += he + gap;
    });
  }
  watch(host, () => draw());
  tween(1300, p => draw(p));
}

// Growth against margin, bubble size = revenue. rows: [{ticker, name, x, y, size, me}]
export function bubbles(host, tip, rows, opts) {
  const svg = el("svg", { role: "img", "aria-label": "Revenue growth against net margin" }, host);
  let current = rows, cancel = () => {}, prev = new Map();
  function draw(progress = 1, from = new Map()) {
    const r = host.getBoundingClientRect(), w = r.width, h = r.height; if (!w) return;
    const g = { l: 52, r: 24, t: 20, b: 44 }; svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.textContent = "";
    const xs = current.map(d => d.x), ys = current.map(d => d.y);
    const xt = niceTicks(Math.min(0, ...xs) - .03, Math.max(...xs) + .03, 5), yt = niceTicks(Math.min(0, ...ys) - .03, Math.max(...ys) + .05, 4);
    const [xl, xh, yl, yh] = [xt[0], xt.at(-1), yt[0], yt.at(-1)];
    const X = v => g.l + (v - xl) / (xh - xl) * (w - g.l - g.r), Y = v => g.t + (1 - (v - yl) / (yh - yl)) * (h - g.t - g.b);
    const faint = css("--faint");
    yt.forEach(v => { el("line", { x1: g.l, x2: w - g.r, y1: Y(v), y2: Y(v), stroke: css("--line") }, svg);
      el("text", { x: g.l - 8, y: Y(v) + 4, "text-anchor": "end", fill: faint, "font-size": 11 }, svg).textContent = Math.round(v * 100) + "%"; });
    xt.forEach(v => el("text", { x: X(v), y: h - 22, "text-anchor": "middle", fill: faint, "font-size": 11 }, svg).textContent = (v > 0 ? "+" : "") + Math.round(v * 100) + "%");
    el("line", { x1: X(0), x2: X(0), y1: g.t, y2: h - g.b, stroke: css("--line-2"), "stroke-dasharray": "3 4" }, svg);
    el("text", { x: w - g.r, y: h - 4, "text-anchor": "end", fill: faint, "font-size": 11 }, svg).textContent = "revenue growth →";
    el("text", { x: g.l + 6, y: g.t + 4, fill: faint, "font-size": 11 }, svg).textContent = "↑ net margin";
    const maxS = Math.max(...current.map(d => d.size || 0)) || 1, maxR = Math.max(16, Math.min(46, w / 22));
    [...current].sort((a, b) => b.size - a.size).forEach(d => {
      const f = from.get(d.ticker) || { x: 0, y: (yl + yh) / 2, r: 0 };
      const rad = Math.max(14, Math.sqrt((d.size || 0) / maxS) * maxR);
      const cx = X(f.x + (d.x - f.x) * progress), cy = Y(f.y + (d.y - f.y) * progress), rr = f.r + (rad - f.r) * progress;
      const col = d.me ? "var(--brand)" : "#6f7f9c";
      const c = el("circle", { cx, cy, r: rr, fill: col, "fill-opacity": d.me ? .85 : .35, stroke: d.me ? css("--fg") : col, "stroke-width": d.me ? 2 : 1, style: "cursor:pointer; transition: fill-opacity .2s" }, svg);
      el("text", { x: cx, y: cy + 4, "text-anchor": "middle", fill: "#fff", "font-size": 11.5, "font-family": "Sora", "pointer-events": "none" }, svg).textContent = d.ticker;
      c.addEventListener("pointerenter", () => { c.setAttribute("fill-opacity", .95); tipAt(tip, cx, cy - rr, opts.tipText(d)); });
      c.addEventListener("pointerleave", () => { c.setAttribute("fill-opacity", d.me ? .85 : .35); tip.style.opacity = 0; });
      prev.set(d.ticker, { x: d.x, y: d.y, r: rad });
    });
  }
  watch(host, () => draw());
  const api = { set(next) { const from = new Map(prev); current = next; cancel(); cancel = tween(900, p => draw(p, from)); } };
  api.set(rows);
  return api;
}
