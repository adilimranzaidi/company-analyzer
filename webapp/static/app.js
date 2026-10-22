// Company Analyzer: the page. It asks the server for data, draws it, and never calculates
// a figure itself (Python did that). Speed rules:
//   - one request for a company's core figures, drawn as soon as it arrives;
//   - the other panels' data is fetched in the background, so a panel is ready when opened;
//   - a panel is drawn only the first time it's opened (then kept);
//   - everything already fetched is kept, so going back to a company is instant;
//   - switching company cancels requests still running for the old one.
import { periodChart, timeChart, sparkline, ring, sankey, bubbles, tween, reduceMotion } from "/static/charts.js";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const html = (s) => { const t = document.createElement("template"); t.innerHTML = s.trim(); return t.content.firstElementChild; };
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } } };

// ---------- Formatting (same rules as analyzer/charts.py) ----------
function money(v, unit = "USD") {
  if (v == null) return "–";
  if (unit === "USD/shares") return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const s = v < 0 ? "-" : "", a = Math.abs(v);
  for (const [size, suf] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (a >= size) return `${s}$${(a / size).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${suf}`;
  return `${s}$${Math.round(a).toLocaleString("en-US")}`;
}
const ratio = v => v == null ? "–" : (v * 100).toFixed(1) + "%";
const pct = v => v == null ? "n/m" : (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
const fmt = (v, unit) => unit === "ratio" ? ratio(v) : money(v, unit);
const shortPeriod = p => p.replace(/ FY(\d{2})(\d{2})/, " '$2").replace(/^FY(\d{4})$/, "$1");
const dateText = iso => iso ? new Date(iso + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";

// ---------- Fetching ----------
let inflight = 0;
function busy(on) { inflight += on ? 1 : -1; const p = $("progress"); p.classList.toggle("on", inflight > 0); p.classList.toggle("done", inflight === 0); }
async function api(path, signal) {
  busy(true);
  try { const r = await fetch(path, { signal }); const data = await r.json(); if (!r.ok) throw new Error(data.error || r.statusText); return data; }
  finally { busy(false); }
}
// Reads a live stream of {type,...} lines from the assistant.
async function stream(path, body, onMsg, signal) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}), signal });
  const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;) { const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true }); let i;
    while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line.trim()) onMsg(JSON.parse(line)); } }
}

// ---------- Answers: light markdown with clickable [n] sources ----------
function markdown(text) {
  const lines = esc(text).split("\n"); let out = "", list = false;
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[(\d+)\]/g, '<button class="ref" data-ref="$1" aria-label="Source $1">$1</button>');
  for (const raw of lines) { const l = raw.trim();
    if (/^[-*•] /.test(l)) { if (!list) { out += "<ul>"; list = true; } out += `<li>${inline(l.slice(2))}</li>`; continue; }
    if (list) { out += "</ul>"; list = false; }
    if (/^#{1,4} /.test(l)) out += `<h4>${inline(l.replace(/^#+ /, ""))}</h4>`; else if (l) out += `<p>${inline(l)}</p>`; }
  return out + (list ? "</ul>" : "");
}
function sourcesHtml(sources) {
  if (!sources?.length) return "";
  return `<details class="sources"><summary class="faint">Sources (${sources.length})</summary>${sources.map(s =>
    `<div class="source" data-src="${s.number}"><b>[${s.number}]</b> ${esc(s.title)}${s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">Open filing</a>` : ""}<blockquote>${esc(s.quote.length > 420 ? s.quote.slice(0, 420) + "…" : s.quote)}</blockquote></div>`).join("")}</details>`;
}
function costText(a) { if (a.saved) return "Saved answer, free to reopen."; const c = a.cost * 100; return `Cost of this answer: ${c < 1 ? c.toFixed(2) : c.toFixed(1)}¢${a.note ? " · " + esc(a.note) : ""}`; }
// Clicking a [n] marker opens and highlights that source.
document.addEventListener("click", e => {
  const b = e.target.closest(".ref"); if (!b) return;
  const box = b.closest("[data-answer]"); const det = box?.querySelector(".sources"); if (!det) return;
  det.open = true; const s = det.querySelector(`[data-src="${b.dataset.ref}"]`);
  if (s) { s.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" }); s.classList.add("hl"); setTimeout(() => s.classList.remove("hl"), 1600); }
});

// One reusable "explain" box: shows a saved answer, or a button that writes one live.
function explainBox(host, ticker, kind, id, label = "Explain from the filings") {
  host.innerHTML = `<div class="faint">Checking for a saved explanation…</div>`;
  api(`/api/explain/${ticker}?kind=${kind}&id=${encodeURIComponent(id)}`).then(s => {
    if (s.answer) return showAnswer(host, s.answer);
    if (!s.can_write) { host.innerHTML = `<div class="faint">Add an Anthropic API key to get explanations.</div>`; return; }
    host.innerHTML = `<button class="chip pressable">${label}</button> <span class="faint">Reads the filings that cover it. Under half a cent.</span>`;
    host.querySelector("button").onclick = () => runAnswer(host, `/api/explain/${ticker}`, { kind, id });
  }).catch(err => { host.innerHTML = `<div class="error">${esc(err.message)}</div>`; });
}
function showAnswer(host, a) {
  host.dataset.answer = ""; host.innerHTML = `<div class="prose">${markdown(a.text)}</div>${sourcesHtml(a.sources)}<div class="faint" style="margin-top:6px">${costText(a)}</div>`;
}
async function runAnswer(host, path, body) {
  host.innerHTML = `<div class="status">Starting…</div><div class="prose typing" hidden></div>`;
  const status = host.querySelector(".status"), live = host.querySelector(".prose"); let text = "";
  try {
    await stream(path, body, m => {
      if (m.type === "status") status.textContent = m.message;
      else if (m.type === "text") { status.hidden = true; live.hidden = false; text += m.chunk; live.innerHTML = markdown(text); }
      else if (m.type === "answer") showAnswer(host, m.answer);
      else if (m.type === "error") host.innerHTML = `<div class="error">${esc(m.message)}</div>`;
    });
  } catch (err) { host.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
}

// ---------- Brand colour from the logo ----------
function brandFrom(img) {
  try {
    const c = document.createElement("canvas"), n = 40; c.width = c.height = n; const x = c.getContext("2d", { willReadFrequently: true });
    x.drawImage(img, 0, 0, n, n); const d = x.getImageData(0, 0, n, n).data, bins = new Array(36).fill(0), sat = new Array(36).fill(0);
    for (let i = 0; i < d.length; i += 4) { if (d[i + 3] < 128) continue;
      const r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, dl = mx - mn;
      if (dl < .2 || l < .12 || l > .92) continue;
      let h = mx === r ? ((g - b) / dl) % 6 : mx === g ? (b - r) / dl + 2 : (r - g) / dl + 4; h = (h * 60 + 360) % 360;
      const k = Math.floor(h / 10); bins[k]++; sat[k] += dl / (1 - Math.abs(2 * l - 1) || 1); }
    let best = bins.indexOf(Math.max(...bins)); if (bins[best] < 12) return null;
    // Red also means "a fall" on this page. If the logo's main colour is red but it has a
    // strong second colour (McDonald's yellow), use that instead.
    const isRed = k => k <= 1 || k >= 34;
    if (isRed(best)) {
      const alt = bins.map((n, k) => (isRed(k) ? 0 : n)), second = alt.indexOf(Math.max(...alt));
      if (alt[second] >= bins[best] * .08) best = second;     // McDonald's yellow is ~11%
    }
    const hue = best * 10 + 5, s = Math.min(85, Math.max(55, sat[best] / bins[best] * 100));
    return `hsl(${hue} ${s.toFixed(0)}% 62%)`;
  } catch { return null; }
}
function setBrand(color) { document.documentElement.style.setProperty("--brand", color || "#3d8bff"); }

// ---------- Panels ----------
const PANELS = [
  { id: "snapshot", title: "Snapshot" }, { id: "briefing", title: "Briefing" }, { id: "trends", title: "Trends" },
  { id: "flow", title: "Where the money goes" }, { id: "price", title: "Price and events" },
  { id: "rivals", title: "Rivals" }, { id: "filings", title: "Filings" },
];
const stage = $("stage"), nav = $("nav"), pill = $("pill"), dots = $("dots");
PANELS.forEach((p, i) => {
  const b = html(`<button role="tab" aria-selected="false" aria-controls="p-${p.id}" id="t-${p.id}">${p.title}</button>`);
  b.onclick = () => go(i); nav.appendChild(b);
  stage.appendChild(html(`<section class="panel" id="p-${p.id}" role="tabpanel" aria-labelledby="t-${p.id}" tabindex="-1"><div class="panel-in"></div></section>`));
  const d = html(`<button aria-label="${p.title}"></button>`); d.onclick = () => go(i); dots.appendChild(d);
});
const tabs = [...nav.querySelectorAll("button")], dotBtns = [...dots.children];
const inner = id => document.querySelector(`#p-${id} .panel-in`);

let S = { ticker: null, data: {}, rendered: new Set(), current: 0, ctrl: null };
const cache = new Map();          // ticker -> {company, price, events, peers, filings, briefing}

function go(i, smooth = true) { stage.scrollTo({ left: i * stage.clientWidth, behavior: smooth && !reduceMotion ? "smooth" : "auto" }); setActive(i); }
function setActive(i) {
  if (i === S.current && S.rendered.has(PANELS[i].id)) { placePill(i); return; }
  S.current = i; tabs.forEach((t, j) => t.setAttribute("aria-selected", j === i)); dotBtns.forEach((d, j) => d.classList.toggle("on", j === i));
  placePill(i); tabs[i].scrollIntoView({ block: "nearest", inline: "nearest" });
  if (S.ticker) { history.replaceState(null, "", `#${S.ticker}/${PANELS[i].id}`); renderPanel(PANELS[i].id); }
}
function placePill(i) { const t = tabs[i]; pill.style.width = t.offsetWidth + "px"; pill.style.transform = `translateX(${t.offsetLeft}px)`; }
let scrollRaf; stage.addEventListener("scroll", () => { cancelAnimationFrame(scrollRaf); scrollRaf = requestAnimationFrame(() => setActive(Math.round(stage.scrollLeft / stage.clientWidth))); }, { passive: true });
addEventListener("resize", () => { placePill(S.current); stage.scrollLeft = S.current * stage.clientWidth; });
addEventListener("keydown", e => {
  if (e.target.closest("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "/") { e.preventDefault(); openSearch(); }
  else if (e.key === "ArrowRight" && S.current < PANELS.length - 1 && !document.querySelector(".drawer.on")) go(S.current + 1);
  else if (e.key === "ArrowLeft" && S.current > 0 && !document.querySelector(".drawer.on")) go(S.current - 1);
  else if (e.key === "Escape") closeAll();
});
$("simple").onclick = () => { const on = $("simple").getAttribute("aria-checked") !== "true"; $("simple").setAttribute("aria-checked", on); document.body.classList.toggle("simple-on", on); store.set("simple", on); };
if (store.get("simple", false)) { $("simple").setAttribute("aria-checked", true); document.body.classList.add("simple-on"); }

// Data each panel needs (fetched in the background after the company loads).
const NEEDS = { snapshot: ["company"], briefing: ["briefing"], trends: ["company"], flow: ["company"], price: ["price", "events"], rivals: ["peers"], filings: ["filings"] };
const URLS = { company: t => `/api/company/${t}`, price: t => `/api/price/${t}`, events: t => `/api/events/${t}`,
  peers: t => `/api/peers/${t}` + ((store.get("peers:" + t, null) || []).length ? `?tickers=${store.get("peers:" + t).join(",")}` : ""),
  filings: t => `/api/filings/${t}`, briefing: t => `/api/briefing/${t}` };
function need(kind, ticker = S.ticker) {
  const c = cache.get(ticker); if (c[kind]) return c[kind];
  c[kind] = api(URLS[kind](ticker), S.ctrl.signal).catch(err => { delete c[kind]; throw err; });
  return c[kind];
}

async function renderPanel(id) {
  if (S.rendered.has(id) || !S.ticker) return;
  S.rendered.add(id); const host = inner(id), ticker = S.ticker;
  try {
    const parts = await Promise.all(NEEDS[id].map(k => need(k)));
    if (ticker !== S.ticker) return;
    const d = Object.fromEntries(NEEDS[id].map((k, i) => [k, parts[i]]));
    RENDER[id](host, d, ticker);
  } catch (err) {
    if (err.name === "AbortError") return; S.rendered.delete(id);
    host.innerHTML = `<div class="error">Couldn't load this view: ${esc(err.message)}. <button class="chip pressable" id="retry-${id}">Try again</button></div>`;
    $("retry-" + id).onclick = () => renderPanel(id);
  }
}

// ---------- Loading a company ----------
async function load(ticker, panel) {
  ticker = ticker.toUpperCase(); if (ticker === S.ticker) return;
  S.ctrl?.abort(); S.ctrl = new AbortController(); closeAll();
  if (!cache.has(ticker)) cache.set(ticker, {});
  S.ticker = ticker; S.rendered = new Set(); store.set("last", ticker);
  PANELS.forEach(p => { inner(p.id).innerHTML = skeleton(p.id); });
  header(null, ticker);
  const idx = Math.max(0, PANELS.findIndex(p => p.id === panel));
  history.replaceState(null, "", `#${ticker}/${PANELS[idx].id}`);
  go(idx, false); renderPanel(PANELS[idx].id);
  try {
    const company = await need("company");
    if (S.ticker !== ticker) return;
    header(company, ticker);
    need("price").then(p => { if (S.ticker === ticker) priceHeader(p); }).catch(() => {});
    // Fetch the rest while the reader looks at the first panel.
    const idle = window.requestIdleCallback || (f => setTimeout(f, 300));
    idle(() => ["events", "briefing", "filings", "peers"].forEach(k => need(k).catch(() => {})));
    // Once the page has been quiet a while, start reading filings for the chat too.
    setTimeout(() => { if (S.ticker === ticker) idle(() => warmChat(ticker)); }, 12000);
  } catch (err) {
    if (err.name === "AbortError") return;
    $("co-name").textContent = ticker; $("co-meta").textContent = "Couldn't load this company: " + err.message;
  }
}
function skeleton(id) {
  const block = (h, extra = "") => `<div class="skel" style="height:${h}px;${extra}"></div>`;
  return `${block(30, "width:40%;margin-bottom:10px")}${block(18, "width:60%;margin-bottom:22px")}` +
    (id === "snapshot" ? `<div class="grid kpis">${block(132).repeat(4)}</div><div class="grid split">${block(360)}${block(360)}</div>` : block(380));
}
function header(c, ticker) {
  const name = c?.company.name || ticker;
  document.title = `${name} · Company Analyzer`;
  $("co-name").textContent = name;
  $("mono").textContent = ticker.slice(0, 4);
  if (!c) { $("co-meta").textContent = "Loading…"; $("px").innerHTML = "&nbsp;"; $("chg").innerHTML = "&nbsp;"; $("spark").textContent = ""; setBrand(null); }
  else {
    const co = c.company, cap = co.market_cap ? ` · ${money(co.market_cap * 1e6)} market value` : "";
    $("co-meta").innerHTML = `${esc(co.ticker)} · ${esc(co.exchange || "")} · ${esc(co.industry)}${cap} · <a href="${esc(co.edgar_url)}" target="_blank" rel="noopener">SEC filings</a>`;
  }
  const img = $("logo-img"); img.classList.remove("on"); img.removeAttribute("src");
  if (c && c.company.has_logo === false) return;
  img.onload = () => { img.classList.add("on"); $("mono").textContent = ""; setBrand(brandFrom(img)); };
  img.onerror = () => {};
  img.src = `/api/logo/${ticker}`;
}
function priceHeader(p) {
  if (!p.series?.length) { $("px").textContent = ""; $("chg").textContent = p.error || ""; return; }
  const target = p.last;
  tween(900, k => { $("px").textContent = "$" + (target * k).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); });
  const c = p.change_1y; $("chg").textContent = c == null ? "" : `${pct(c)} over the last year`; $("chg").className = "chg " + (c >= 0 ? "up" : "down");
  const year = p.series.slice(-252).map(r => r[1]); sparkline($("spark"), year, c >= 0 ? "var(--up)" : "var(--down)", true);
}

// ---------- Panel: Snapshot ----------
const RENDER = {};
RENDER.snapshot = (host, { company: c }, ticker) => {
  const k = c.kpis, cards = k.cards;
  host.innerHTML = `<h2>${k.period ? esc(k.period.replace(/ FY/, " ")) + " at a glance" : "At a glance"}</h2>
    <p class="lede">Latest quarter, ${esc(k.source)}. Tap a figure to chart it. Every figure is from SEC filings, calculated in Python.</p>
    <div class="grid kpis" id="kpis"></div>
    <div class="grid split">
      <div class="card"><div class="card-head"><h3 id="snap-title"></h3><div class="seg" id="snap-seg"><button aria-pressed="true" data-q="1">Quarterly</button><button aria-pressed="false" data-q="0">Annual</button></div></div>
        <div class="chart" id="snap-chart"><div class="tip"></div></div><div class="faint" id="snap-note"></div></div>
      <div class="card"><h3>What to take away</h3><div id="takes" style="margin-top:6px"></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>Latest notable events</h3><button class="chip pressable" id="to-events">All events</button></div><div class="rows" id="snap-events" style="margin-top:6px"><div class="skel" style="height:120px"></div></div></div>`;
  const chartHost = $("snap-chart"), chart = periodChart(chartHost, chartHost.querySelector(".tip"));
  let key = cards[0]?.key, quarterly = true;
  function show() {
    const s = c.series[key]; if (!s) return;
    const rows = (quarterly ? s.quarterly : s.annual).slice(quarterly ? -12 : -10);
    $("snap-title").textContent = `${s.name}, last ${rows.length} ${quarterly ? "quarters" : "years"}`;
    chart.set({ points: rows.map(r => ({ label: r.p, short: shortPeriod(r.p), value: r.v, flag: r.flag, yoy: r.yoy, src: r.src })),
      format: v => fmt(v, s.unit), zeroBase: s.unit !== "ratio" && s.unit !== "USD/shares" ? false : false,
      tipText: p => `${esc(p.label)}<b>${fmt(p.value, s.unit)}</b>${p.yoy != null ? pct(p.yoy) + " vs a year earlier" : ""}${p.flag ? "<br>Unusual change: open Trends to read why" : ""}`,
      onFlag: () => go(PANELS.findIndex(p => p.id === "trends")) });
    const derived = rows.some(r => /Derived/.test(r.src || ""));
    $("snap-note").textContent = derived ? "Some Q4 figures are derived: full year minus the first three quarters." : "";
  }
  cards.forEach((card, i) => {
    const ch = card.change, cls = !ch ? "faint" : ch.kind === "points" ? "faint" : ch.value >= 0 ? "up" : "down";
    const chText = !ch ? "no comparison" : ch.kind === "points" ? `${ch.value >= 0 ? "+" : "−"}${Math.abs(ch.value).toFixed(1)} points vs a year ago` : `${ch.value >= 0 ? "+" : "−"}${Math.abs(ch.value).toFixed(1)}% vs a year ago`;
    const b = html(`<button class="kpi pressable" aria-pressed="${i === 0}"><div class="lab">${esc(card.label)}</div><div class="val">${fmt(0, card.unit)}</div><div class="dl ${cls}">${chText}</div><svg viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true"></svg><div class="say"><div>${esc(card.help)}</div></div></button>`);
    $("kpis").appendChild(b);
    const val = b.querySelector(".val"); setTimeout(() => tween(950, p => { val.textContent = fmt(card.value * p, card.unit); }), i * 80);
    sparkline(b.querySelector("svg"), card.spark, "var(--brand)");
    b.onclick = () => { [...$("kpis").children].forEach(x => x.setAttribute("aria-pressed", x === b)); key = card.key; show(); };
  });
  $("snap-seg").onclick = e => { const b = e.target.closest("button"); if (!b) return; quarterly = b.dataset.q === "1"; [...$("snap-seg").children].forEach(x => x.setAttribute("aria-pressed", x === b)); show(); };
  show();
  const takes = [...c.takeaways]; const draw = () => { $("takes").innerHTML = takes.map(t => `<div class="take"><svg class="ring"></svg><div><p>${esc(t.title)}</p><span>${esc(t.detail)}</span></div></div>`).join("");
    [...$("takes").querySelectorAll(".ring")].forEach((r, i) => ring(r, takes[i].fill, takes[i].tone === "up" ? "var(--up)" : takes[i].tone === "down" ? "var(--down)" : "var(--brand)", 200 + i * 110)); };
  draw();
  need("price", ticker).then(p => { if (p.change_1y == null || ticker !== S.ticker) return; const up = p.change_1y >= 0;
    takes.push({ tone: up ? "up" : "down", fill: Math.min(100, Math.abs(p.change_1y) * 100), title: `The stock is ${up ? "up" : "down"} ${Math.abs(p.change_1y * 100).toFixed(1)}% over the last year`, detail: "See Price and events for the days that moved it most." }); draw(); }).catch(() => {});
  $("to-events").onclick = () => go(PANELS.findIndex(p => p.id === "price"));
  need("events", ticker).then(ev => { if (ticker !== S.ticker) return;
    const rows = ev.events.slice(0, 4);
    $("snap-events").innerHTML = rows.length ? rows.map(e => `<div class="row"><span>${esc(e.title)}</span><span class="r">${dateText(e.date)}</span></div>`).join("") : `<div class="faint">No notable events in the last 5 years.</div>`;
    if (c.unusual[0]) $("snap-events").insertAdjacentHTML("beforeend", `<div class="faint" style="padding-top:8px">Latest unusual change in the financials: ${esc(c.unusual[0].metric)}, ${esc(c.unusual[0].period)}.</div>`);
  }).catch(() => { $("snap-events").innerHTML = `<div class="faint">Events couldn't be loaded.</div>`; });
};

// ---------- Panel: Briefing ----------
RENDER.briefing = (host, { briefing: b }, ticker) => {
  const head = `<h2>Company briefing</h2><p class="lede">What the company does, how it makes money, its latest quarter, recent events, key risks and interview talking points, from its own filings. Every point has a numbered source.</p>`;
  if (!b.available) { host.innerHTML = head + `<div class="empty">${esc(b.reason)}</div>`; return; }
  const show = a => {
    const parts = a.text.split(/^### /m).filter(s => s.trim());
    host.innerHTML = head + `<div class="faint" style="margin:-10px 0 16px">Written from the ${esc(b.based_on)}. A new briefing can be written when the company files its next report.</div>
      <div data-answer><div class="grid brief">${parts.map(p => { const [title, ...rest] = p.split("\n");
        return `<div class="card"><h3>${esc(title.trim())}</h3><div class="prose">${markdown(rest.join("\n"))}</div></div>`; }).join("")}</div>
      <div class="card" style="margin-top:16px">${sourcesHtml(a.sources).replace("<details", "<details open")}<div class="faint" style="margin-top:6px">${costText(a)}</div></div></div>`;
  };
  if (b.answer) return show(b.answer);
  host.innerHTML = head + `<div class="card" id="brief-box"><p>A briefing hasn't been written for ${esc(ticker)}'s latest filings yet.</p>
    ${b.can_write ? `<button class="icon-btn primary pressable" id="write-brief">Write the briefing</button> <span class="faint">Reads the ${esc(b.based_on)}. About 25 seconds and under 1¢, then saved.</span>` : `<div class="faint">Add an Anthropic API key to write it.</div>`}</div>`;
  const btn = $("write-brief"); if (!btn) return;
  btn.onclick = async () => {
    const box = $("brief-box"); box.innerHTML = `<div class="status">Starting…</div><div class="prose typing" hidden></div>`;
    const st = box.querySelector(".status"), live = box.querySelector(".prose"); let text = "";
    try { await stream(`/api/briefing/${ticker}`, {}, m => {
        if (m.type === "status") st.textContent = m.message;
        else if (m.type === "text") { st.hidden = true; live.hidden = false; text += m.chunk; live.innerHTML = markdown(text); }
        else if (m.type === "answer") { cache.get(ticker).briefing = Promise.resolve({ ...b, answer: m.answer }); show(m.answer); }
        else if (m.type === "error") box.innerHTML = `<div class="error">${esc(m.message)}</div>`; });
    } catch (err) { box.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
  };
};

// ---------- Panel: Trends ----------
RENDER.trends = (host, { company: c }, ticker) => {
  const keys = Object.keys(c.series), order = ["revenue", "net_income", "eps_diluted", "net_margin", "operating_margin", "gross_margin", "roe"];
  keys.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  host.innerHTML = `<h2>Trends</h2><p class="lede">Every figure we track, over time. Orange dots are unusual changes for this company, judged against its own history; tap one to read management's explanation.</p>
    <div class="chips" id="tr-chips">${keys.map((k, i) => `<button class="chip pressable" aria-pressed="${i === 0}" data-k="${k}">${esc(c.series[k].name)}</button>`).join("")}</div>
    <div class="grid split">
      <div class="card"><div class="card-head"><h3 id="tr-title"></h3><div style="display:flex;gap:8px;flex-wrap:wrap">
        <div class="seg" id="tr-period"><button aria-pressed="true" data-q="1">Quarterly</button><button aria-pressed="false" data-q="0">Annual</button></div>
        <div class="seg" id="tr-range"><button aria-pressed="false" data-n="3">3Y</button><button aria-pressed="true" data-n="5">5Y</button><button aria-pressed="false" data-n="10">10Y</button><button aria-pressed="false" data-n="99">All</button></div></div></div>
        <div class="chart" id="tr-chart" style="height:340px"><div class="tip"></div></div></div>
      <div class="card" id="tr-about"></div>
    </div>
    <div class="grid split">
      <div class="card"><h3>Figures</h3><div class="table-wrap" id="tr-table" style="margin-top:10px"></div></div>
      <div class="card"><h3>Unusual changes</h3><div id="tr-unusual" style="margin-top:6px"></div></div>
    </div>`;
  const chartHost = $("tr-chart"), chart = periodChart(chartHost, chartHost.querySelector(".tip"));
  let key = keys[0], quarterly = true, years = 5;
  function show() {
    const s = c.series[key], all = quarterly ? s.quarterly : s.annual, rows = all.slice(-(years * (quarterly ? 4 : 1)));
    $("tr-title").textContent = s.name;
    if (!rows.length) { chartHost.querySelector("svg") && (chartHost.querySelector("svg").textContent = ""); $("tr-table").innerHTML = `<div class="empty">${esc(s.note || "No " + (quarterly ? "quarterly" : "annual") + " figures reported.")}</div>`; return; }
    chart.set({ points: rows.map(r => ({ label: r.p, short: shortPeriod(r.p), value: r.v, flag: r.flag, yoy: r.yoy })), format: v => fmt(v, s.unit),
      tipText: p => `${esc(p.label)}<b>${fmt(p.value, s.unit)}</b>${p.yoy != null ? pct(p.yoy) + " vs a year earlier" : ""}`,
      onFlag: p => openUnusual(key, p.label) });
    const last = rows.at(-1);
    $("tr-about").innerHTML = `<h3>${esc(s.name)}</h3><div style="font:500 30px var(--display);margin:6px 0 2px">${fmt(last.v, s.unit)}</div>
      <div class="${last.yoy == null ? "faint" : last.yoy >= 0 ? "up" : "down"}" style="font-size:13px">${last.yoy != null ? pct(last.yoy) + " vs a year earlier" : esc(last.p)}</div>
      <p class="muted" style="font-size:14px">${esc(s.description || "")}</p>
      ${s.formula ? `<div class="faint">Formula: ${esc(s.formula)}</div>` : ""}
      ${s.label ? `<div class="faint">EDGAR label: ${esc(s.label)}</div>` : ""}
      ${s.note ? `<div class="faint">${esc(s.note)}</div>` : ""}
      ${rows.some(r => /Derived/.test(r.src || "")) ? `<div class="faint">Some Q4 figures are derived: full year minus Q1, Q2 and Q3.</div>` : ""}
      ${key === "eps_diluted" && quarterly ? `<div class="faint">Q4 EPS isn't derived: per-share figures can't be subtracted when the share count changes.</div>` : ""}`;
    $("tr-table").innerHTML = `<table><thead><tr><th>Period</th><th class="n">Value</th>${s.kind === "metric" ? `<th class="n">vs a year earlier</th>` : ""}<th>Source</th></tr></thead><tbody>${[...rows].reverse().map(r =>
      `<tr><td>${esc(r.p)}${r.flag ? ' <span class="tag flag">unusual</span>' : ""}</td><td class="n">${fmt(r.v, s.unit)}</td>${s.kind === "metric" ? `<td class="n ${r.yoy == null ? "" : r.yoy >= 0 ? "up" : "down"}">${pct(r.yoy)}</td>` : ""}<td class="faint">${esc(r.src || "")}</td></tr>`).join("")}</tbody></table>`;
  }
  const seg = (id, fn) => { $(id).onclick = e => { const b = e.target.closest("button"); if (!b) return; [...$(id).children].forEach(x => x.setAttribute("aria-pressed", x === b)); fn(b); show(); }; };
  seg("tr-period", b => { quarterly = b.dataset.q === "1"; renderUnusual(); }); seg("tr-range", b => { years = +b.dataset.n; });
  $("tr-chips").onclick = e => { const b = e.target.closest("button"); if (!b) return; [...$("tr-chips").children].forEach(x => x.setAttribute("aria-pressed", x === b)); key = b.dataset.k; show(); };
  function renderUnusual() {
    const list = quarterly ? c.unusual : c.unusual_annual;
    $("tr-unusual").innerHTML = list.length ? list.slice(0, 12).map((u, i) => `<div class="row" style="display:block" data-u="${esc(u.metric_key)}|${esc(u.period)}">
      <div style="display:flex;justify-content:space-between;gap:12px"><button class="chip pressable" data-i="${i}" style="height:auto;padding:6px 12px;text-align:left;white-space:normal">${esc(u.period)} · ${esc(u.metric)} ${pct(u.yoy)}</button><span class="r">usually ${pct(u.typical)}</span></div>
      <div class="faint">${fmt(u.value, u.unit)} vs ${fmt(u.prior, u.unit)} a year earlier · first reported in the <a href="${esc(u.filing_url)}" target="_blank" rel="noopener">${esc(u.first_reported)}</a></div>
      <div class="ex" style="margin-top:8px" hidden></div></div>`).join("") : `<div class="empty">No unusual ${quarterly ? "quarterly" : "annual"} changes.</div>`;
    $("tr-unusual").onclick = e => { const b = e.target.closest("button.chip[data-i]"); if (!b) return; const row = b.closest(".row"), ex = row.querySelector(".ex");
      if (!ex.hidden) { ex.hidden = true; return; } ex.hidden = false; explainBox(ex, ticker, "change", row.dataset.u); };
  }
  function openUnusual(metricKey, period) {
    const row = $("tr-unusual").querySelector(`[data-u="${CSS.escape(metricKey + "|" + period)}"]`); if (!row) return;
    row.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" }); const ex = row.querySelector(".ex");
    if (ex.hidden) { ex.hidden = false; explainBox(ex, ticker, "change", row.dataset.u); }
  }
  renderUnusual(); show();
};

// ---------- Panel: Where the money goes ----------
RENDER.flow = (host, { company: c }) => {
  const f = c.flow;
  if (!f) { host.innerHTML = `<h2>Where the money goes</h2><div class="empty" style="margin-top:16px">This view needs revenue and a profit for the same quarter. ${esc(c.company.name)} doesn't have both in its latest quarter (for example, it made a loss), so there's nothing to split.</div>`; return; }
  const parts = f.parts.map(p => `${money(p.value)} ${p.key === "net_income" ? "was left as profit" : p.key === "credit_provision" ? "was set aside for loans that may not be repaid" : p.key === "cost_of_revenue" ? "went on the direct cost of what it sold" : "went on running the business, interest and taxes"}`);
  const colors = { cost_of_revenue: "#7b6cff", credit_provision: "#f2b84b", other: "#56637c", net_income: getComputedStyle(document.documentElement).getPropertyValue("--up").trim() };
  host.innerHTML = `<h2>Where each dollar of revenue went</h2><p class="lede">${esc(f.period)}: of ${money(f.revenue)} taken in, ${parts.slice(0, -1).join(", ")}, and ${parts.at(-1)}.</p>
    <div class="card"><div class="chart flow" id="flow-chart"></div>
    <div class="legend">${f.parts.map(p => `<span><i style="background:${colors[p.key]}"></i>${esc(p.name)}</span>`).join("")}</div>
    <div class="faint" style="margin-top:8px">"Other costs and taxes" is revenue minus the parts the company reports separately, calculated in Python. All amounts are from the same quarter's filing.</div></div>`;
  sankey($("flow-chart"), f, colors, money);
};

// ---------- Panel: Price and events ----------
RENDER.price = (host, { price: p, events: ev }, ticker) => {
  const cats = [...new Set(ev.events.map(e => e.category))];
  host.innerHTML = `<h2>Price and events</h2><p class="lede">Red dots are days the stock moved far more than the market would explain; orange dots are major events the company reported in an 8-K. Tap one.</p>
    <div class="card"><div class="card-head"><h3>Share price</h3><div class="seg" id="pr-range"><button aria-pressed="false" data-d="30">1M</button><button aria-pressed="false" data-d="182">6M</button><button aria-pressed="true" data-d="365">1Y</button><button aria-pressed="false" data-d="1826">5Y</button></div></div>
      ${p.series?.length ? `<div class="chart" id="pr-chart" style="height:330px"><div class="tip"></div></div>` : `<div class="empty" style="margin-top:10px">${esc(p.error || ev.price_note || "No price data.")}</div>`}</div>
    <div class="grid split">
      <div class="card"><div class="card-head"><h3>Notable events</h3><div class="chips" id="ev-chips">${cats.map(k => `<button class="chip pressable" aria-pressed="true" data-c="${esc(k)}">${esc(k)}</button>`).join("")}</div></div><div id="ev-list" style="margin-top:8px"></div></div>
      <div class="card"><h3>Latest headlines</h3><div class="rows" style="margin-top:6px">${ev.headlines.length ? ev.headlines.slice(0, 10).map(a => `<div class="row" style="display:block"><a href="${esc(a.url)}" target="_blank" rel="noopener" style="color:var(--fg)">${esc(a.title)}</a><div class="faint">${esc(a.source)} · ${dateText(a.date)}</div></div>`).join("") : `<div class="faint">${esc(ev.headlines_error || "No recent headlines.")}</div>`}</div></div>
    </div>`;
  const shown = new Set(cats);
  function list() {
    const rows = ev.events.filter(e => shown.has(e.category));
    $("ev-list").innerHTML = rows.length ? rows.map((e, i) => `<div class="row" style="display:block" id="ev-${i}" data-id="${esc(e.id)}" data-date="${e.date}">
      <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap"><span class="faint" style="min-width:92px">${dateText(e.date)}</span><span class="tag ${e.severity === "high" ? "high" : ""}">${esc(e.category)}</span><b style="font-weight:500">${esc(e.title)}</b></div>
      ${e.detail ? `<div class="muted" style="font-size:14px;margin-top:4px">${esc(e.detail)}</div>` : ""}
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap"><button class="chip pressable" data-act="explain">Explain this event</button>${new Date(e.date) > new Date(Date.now() - 365 * 864e5) ? `<button class="chip pressable" data-act="news">Headlines that day</button>` : ""}${e.url ? `<a class="chip" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.form)}</a>` : ""}</div>
      <div class="ex" style="margin-top:8px" hidden></div></div>`).join("") : `<div class="empty">No events of these types.</div>`;
  }
  $("ev-list").onclick = e => { const b = e.target.closest("button[data-act]"); if (!b) return; const row = b.closest(".row"), ex = row.querySelector(".ex"); ex.hidden = false;
    if (b.dataset.act === "explain") explainBox(ex, ticker, "event", row.dataset.id, "Explain this event");
    else { ex.innerHTML = `<div class="status">Fetching headlines…</div>`; api(`/api/around/${ticker}?day=${row.dataset.date}`).then(r => {
      ex.innerHTML = r.headlines.length ? r.headlines.map(a => `<div class="faint"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> · ${esc(a.source)}</div>`).join("") : `<div class="faint">${esc(r.error || "No headlines found for those days.")}</div>`; }); } };
  $("ev-chips").onclick = e => { const b = e.target.closest("button"); if (!b) return; const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", on); on ? shown.add(b.dataset.c) : shown.delete(b.dataset.c); list(); };
  list();
  if (!p.series?.length) return;
  const pts = p.series.map(([d, v]) => [new Date(d + "T00:00").getTime(), v]), end = pts.at(-1)[0];
  const chartHost = $("pr-chart"), chart = timeChart(chartHost, chartHost.querySelector(".tip"));
  const events = ev.events.map(e => ({ ms: new Date(e.date + "T00:00").getTime(), title: e.title, id: e.id, kind: e.category === "Stock move" ? "move" : "event" }));
  const open = item => { const row = [...$("ev-list").children].find(r => r.dataset.id === item.id);
    if (!row) return; row.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" }); row.style.background = "var(--brand-soft)"; setTimeout(() => row.style.background = "", 1600); };
  chart.set({ points: pts, events, onEvent: open, format: v => "$" + v.toLocaleString("en-US", { maximumFractionDigits: v >= 100 ? 0 : 2 }) }, end - 365 * 864e5, end);
  $("pr-range").onclick = e => { const b = e.target.closest("button"); if (!b) return; [...$("pr-range").children].forEach(x => x.setAttribute("aria-pressed", x === b)); chart.zoom(Math.max(pts[0][0], end - b.dataset.d * 864e5), end); };
};

// ---------- Panel: Rivals ----------
RENDER.rivals = (host, { peers: d }, ticker) => {
  const me = d.rows.find(r => r.ticker === ticker), labels = { revenue_growth: "Revenue growth", net_margin: "Net margin", roe: "Return on equity", eps_growth: "EPS growth" };
  const named = d.suggested.filter(s => s.source === "Named in the 10-K");
  host.innerHTML = `<h2>Against rivals</h2><p class="lede">${named.length ? `Named as competitors in ${esc(ticker)}'s 10-K: ${named.map(s => esc(s.ticker)).join(", ")}. ` : ""}Each company's own latest fiscal year. Add or remove companies to change the group.</p>
    <div class="chips" id="peer-chips"></div>
    <div class="grid ranks" style="margin-top:16px">${Object.entries(d.ranks).map(([k, r]) => `<div class="card rank"><div class="faint">${labels[k]}</div><b>${["", "1st", "2nd", "3rd"][r.rank] || r.rank + "th"} of ${r.of}</b><div class="muted" style="font-size:13px">${k.endsWith("growth") ? pct(me?.[k]) : ratio(me?.[k])} · peer median ${k.endsWith("growth") ? pct(r.median) : ratio(r.median)}</div></div>`).join("")}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>Growth against profitability</h3><span class="faint">Bubble size is revenue. Hover a company.</span></div><div class="chart" id="peer-bubbles" style="height:400px"><div class="tip"></div></div></div>
    <div class="card" style="margin-top:16px"><h3>Side by side</h3><div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Company</th><th>Fiscal year</th><th class="n">Revenue</th><th class="n">Revenue growth</th><th class="n">Net margin</th><th class="n">Return on equity</th><th class="n">EPS growth</th></tr></thead><tbody>
      ${d.rows.map(r => `<tr${r.ticker === ticker ? ' style="background:var(--brand-soft)"' : ""}><td>${esc(r.name)} (${esc(r.ticker)})</td><td>${esc(r.fiscal_year || "–")}</td><td class="n">${money(r.revenue)}</td><td class="n">${pct(r.revenue_growth)}</td><td class="n">${ratio(r.net_margin)}</td><td class="n">${ratio(r.roe)}</td><td class="n">${pct(r.eps_growth)}</td></tr>`).join("")}
      <tr><td class="muted">Peer median</td><td></td><td></td><td class="n muted">${pct(d.medians.revenue_growth)}</td><td class="n muted">${ratio(d.medians.net_margin)}</td><td class="n muted">${ratio(d.medians.roe)}</td><td class="n muted">${pct(d.medians.eps_growth)}</td></tr></tbody></table></div>
      ${named.length ? `<details style="margin-top:10px"><summary class="faint">Where the 10-K names them</summary>${named.map(s => `<p class="muted" style="font-size:14px"><b>${esc(s.ticker)}</b>: “${esc(s.evidence)}”</p>`).join("")}</details>` : ""}</div>`;
  const group = d.rows.map(r => r.ticker).filter(t => t !== ticker);
  $("peer-chips").innerHTML = group.map(t => `<span class="chip" aria-pressed="true">${esc(t)} <button aria-label="Remove ${esc(t)}" data-rm="${esc(t)}" style="background:none;border:0;padding:0;color:var(--muted);display:grid"><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button></span>`).join("") + `<button class="chip pressable" id="add-peer">+ Add a company</button>`;
  const reload = list => { store.set("peers:" + ticker, list); delete cache.get(ticker).peers; S.rendered.delete("rivals"); host.innerHTML = skeleton("rivals"); renderPanel("rivals"); };
  $("peer-chips").onclick = e => { const rm = e.target.closest("[data-rm]"); if (rm) reload(group.filter(t => t !== rm.dataset.rm)); };
  $("add-peer").onclick = () => openSearch(t => { if (t !== ticker && !group.includes(t)) reload([...group, t]); });
  const rows = d.rows.filter(r => r.revenue_growth != null && r.net_margin != null).map(r => ({ ticker: r.ticker, name: r.name, x: r.revenue_growth, y: r.net_margin, size: r.revenue, me: r.ticker === ticker }));
  const bh = $("peer-bubbles");
  if (rows.length) bubbles(bh, bh.querySelector(".tip"), rows, { tipText: r => `${esc(r.name)}<b>${pct(r.x)} growth · ${ratio(r.y)} margin</b>${money(r.size)} revenue` });
};

// ---------- Panel: Filings ----------
RENDER.filings = (host, { filings: f }) => {
  const kinds = ["All", "10-K", "10-Q", "8-K", "Other"];
  host.innerHTML = `<h2>Filings</h2><p class="lede">The company's reports to the SEC, newest first. The Ask chat can answer questions from any 10-K or 10-Q.</p>
    <div class="grid kpis" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">${f.latest.map(r => `<a class="card pressable" href="${esc(r.url)}" target="_blank" rel="noopener" style="color:var(--fg);text-decoration:none"><div class="faint">Latest ${r.form.startsWith("10-K") ? "annual" : "quarterly"} report</div><h3 style="font-size:18px;margin:4px 0">${esc(r.form)} · period ending ${dateText(r.period)}</h3><div class="faint">Filed ${dateText(r.filed)} · Open</div></a>`).join("")}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>All filings</h3><div class="seg" id="fl-kind">${kinds.map((k, i) => `<button aria-pressed="${i === 0}" data-k="${k}">${k}</button>`).join("")}</div></div><div class="table-wrap" id="fl-table" style="margin-top:10px"></div></div>`;
  const table = k => { const rows = f.rows.filter(r => k === "All" || (k === "Other" ? !/^(10-K|10-Q|8-K)/.test(r.form) : r.form.startsWith(k))).slice(0, 150);
    $("fl-table").innerHTML = `<table><thead><tr><th>Filed</th><th>Form</th><th>What it is</th><th>Period</th><th></th></tr></thead><tbody>${rows.map(r =>
      `<tr><td style="white-space:nowrap">${dateText(r.filed)}</td><td>${esc(r.form)}</td><td>${esc(r.about || r.form_name)}${r.significant ? ' <span class="tag high">notable</span>' : ""}</td><td style="white-space:nowrap" class="faint">${r.period ? dateText(r.period) : ""}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">Open</a></td></tr>`).join("")}</tbody></table>`; };
  $("fl-kind").onclick = e => { const b = e.target.closest("button"); if (!b) return; [...$("fl-kind").children].forEach(x => x.setAttribute("aria-pressed", x === b)); table(b.dataset.k); };
  table("All");
};

// ---------- Drawers: Ask and Glossary ----------
const scrim = $("scrim");
function openDrawer(id) { closeAll(true); $(id).classList.add("on"); $(id).setAttribute("aria-hidden", "false"); scrim.classList.add("on"); }
function closeAll(keepScrim) { document.querySelectorAll(".drawer.on, .sheet.on").forEach(d => { d.classList.remove("on"); d.setAttribute("aria-hidden", "true"); }); if (!keepScrim) scrim.classList.remove("on"); }
scrim.onclick = () => closeAll(); document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => closeAll());

const chats = new Map();
const warmed = new Set();
const warmChat = t => { if (!t || warmed.has(t)) return; warmed.add(t); fetch(`/api/warm/${t}`, { method: "POST" }).catch(() => {}); };
$("open-ask").onclick = () => { warmChat(S.ticker); openDrawer("ask"); renderChat(); setTimeout(() => $("ask-input").focus(), 350); };
function renderChat() {
  const t = S.ticker, hist = chats.get(t) || [], body = $("ask-body"), name = $("co-name").textContent;
  $("ask-scope").textContent = t || "";
  if (!hist.length) { body.innerHTML = `<p class="muted">Ask about ${esc(name)} or anything on the dashboard. Answers come only from its filings and the dashboard's own figures, with numbered sources; if they don't cover your question, it says so. Name the quarter or year you mean. Each question costs a fraction of a cent. Not investment advice.</p>
    <div class="chips" style="flex-direction:column;align-items:stretch">${[`How does ${name} make money?`, "What drove results in the latest quarter?", `What are the biggest risks ${t} describes?`, "What does return on equity mean, and what is it here?"].map(q => `<button class="chip pressable" style="height:auto;padding:10px 14px;white-space:normal;text-align:left" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`;
    body.onclick = e => { const b = e.target.closest("[data-q]"); if (b) send(b.dataset.q); }; return; }
  body.onclick = null;
  body.innerHTML = hist.map(h => `<div class="msg me">${esc(h.q)}</div><div class="msg" data-answer>${h.a ? `<div class="prose">${markdown(h.a.text)}</div>${sourcesHtml(h.a.sources)}<div class="cost">${costText(h.a)}</div>` : ""}</div>`).join("");
}
$("ask-form").onsubmit = e => { e.preventDefault(); const q = $("ask-input").value.trim(); if (q) { $("ask-input").value = ""; send(q); } };
async function send(q) {
  const t = S.ticker, hist = chats.get(t) || []; chats.set(t, hist);
  const turn = { q, a: null }; hist.push(turn); renderChat();
  const body = $("ask-body"), box = body.lastElementChild; box.innerHTML = `<div class="status">Starting…</div><div class="prose typing" hidden></div>`;
  body.scrollTo({ top: body.scrollHeight, behavior: "smooth" });
  const st = box.querySelector(".status"), live = box.querySelector(".prose"); let text = "";
  try { await stream(`/api/ask/${t}`, { question: q, history: hist.filter(h => h.a).slice(-6).map(h => [h.q, h.a.plain_text || h.a.text]) }, m => {
      if (m.type === "status") st.textContent = m.message;
      else if (m.type === "text") { st.hidden = true; live.hidden = false; text += m.chunk; live.innerHTML = markdown(text); body.scrollTop = body.scrollHeight; }
      else if (m.type === "answer") { turn.a = m.answer; renderChat(); body.scrollTop = body.scrollHeight; }
      else if (m.type === "error") { box.innerHTML = `<div class="error">${esc(m.message)}</div>`; hist.pop(); } });
  } catch (err) { box.innerHTML = `<div class="error">${esc(err.message)}</div>`; hist.pop(); }
}

let glossary = null;
$("open-glossary").onclick = async () => { openDrawer("glossary"); if (!glossary) glossary = await api("/api/glossary"); drawGlossary(""); setTimeout(() => $("gl-input").focus(), 350); };
$("gl-input").oninput = e => drawGlossary(e.target.value);
function drawGlossary(q) { q = q.toLowerCase(); $("gl-body").innerHTML = Object.entries(glossary).filter(([k, v]) => !q || k.toLowerCase().includes(q) || (v.short || "").toLowerCase().includes(q))
  .map(([k, v]) => `<div class="row" style="display:block"><b style="font-weight:500">${esc(k)}</b><div class="muted" style="font-size:14px">${esc(v.short)}</div>${v.long ? `<details><summary class="faint">More</summary><p class="muted" style="font-size:14px">${esc(v.long)}</p></details>` : ""}</div>`).join("") || `<div class="faint">No terms match.</div>`; }

// ---------- Search ----------
let index = null, pick = null, sel = 0;
const loadIndex = () => index ? Promise.resolve(index) : api("/api/search").then(r => (index = r.map(([t, n]) => [t, n, n.toLowerCase()])));
function openSearch(onPick) { pick = onPick || null; $("search").classList.add("on"); $("search").setAttribute("aria-hidden", "false"); scrim.classList.add("on");
  $("search-input").value = ""; $("results").innerHTML = `<div class="faint" style="padding:10px">Type a company name or ticker.</div>`; setTimeout(() => $("search-input").focus(), 50); loadIndex(); }
$("open-search").onclick = () => openSearch();
function matches(q) {
  q = q.trim(); if (!q || !index) return []; const up = q.toUpperCase(), low = q.toLowerCase(), out = [];
  for (const [t, n, nl] of index) { let s = 0;
    if (t === up) s = 100; else if (t.startsWith(up)) s = 80 - t.length; else if (nl.startsWith(low)) s = 60; else if (nl.includes(" " + low)) s = 45; else if (nl.includes(low)) s = 30;
    if (s) out.push([s, t, n]); if (out.length > 400) break; }
  return out.sort((a, b) => b[0] - a[0]).slice(0, 30);
}
$("search-input").oninput = async e => { await loadIndex(); const m = matches(e.target.value); sel = 0;
  $("results").innerHTML = m.length ? m.map(([, t, n], i) => `<button class="result" role="option" aria-selected="${i === 0}" data-t="${esc(t)}"><b>${esc(t)}</b><span>${esc(n)}</span></button>`).join("") : `<div class="faint" style="padding:10px">No company matches “${esc(e.target.value)}”.</div>`; };
$("search-input").onkeydown = e => { const items = [...$("results").querySelectorAll(".result")]; if (!items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; items.forEach((x, i) => x.setAttribute("aria-selected", i === sel)); items[sel].scrollIntoView({ block: "nearest" }); }
  if (e.key === "Enter") { e.preventDefault(); choose(items[sel].dataset.t); } };
$("results").onclick = e => { const b = e.target.closest(".result"); if (b) choose(b.dataset.t); };
function choose(t) { closeAll(); if (pick) { const f = pick; pick = null; f(t); } else load(t, PANELS[S.current].id); }

// ---------- Start ----------
function fromHash() { const [t, p] = decodeURIComponent(location.hash.slice(1)).split("/"); return [t || store.get("last", "AXP"), p || "snapshot"]; }
addEventListener("hashchange", () => { const [t, p] = fromHash(); if (t.toUpperCase() !== S.ticker) load(t, p); else go(Math.max(0, PANELS.findIndex(x => x.id === p))); });
requestAnimationFrame(() => { const [t, p] = fromHash(); load(t, p); });
// Load the company list for search in a quiet moment, so the first search is instant.
setTimeout(() => (window.requestIdleCallback || (f => f()))(() => loadIndex().catch(() => {})), 2500);
