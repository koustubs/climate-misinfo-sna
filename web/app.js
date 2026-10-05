/* Climate Misinformation SNA - front end (vanilla JS + Chart.js) */
"use strict";

// ------------------------------------------------------------------ constants & helpers
const C = {
  plum: "#3F2C47", plum6: "#7A4966", gold: "#B77D22", ink: "#2E2733", ink2: "#5B5360",
  muted: "#8A828D", line: "#E9E2D8", grid: "#F1ECE4", ok: "#3E7D5A", bad: "#B24A3B",
};
const STRAT_COLOR = {
  random: "#A39BA6", degree: "#7A4966", bridge: "#B77D22",
  pagerank: "#4F7C82", detector: "#C0624B", detector_reach: "#6B7F3A",
};
const COMM_COLORS = ["#7A4966", "#B77D22", "#4F7C82", "#C0624B", "#6B7F3A", "#3F5E8C", "#A45C8C", "#8C6D4F"];
const OTHER_COLOR = "#CFC7D2";
const GROUP_COLOR = { behaviour: "#A39BA6", structure: "#7A4966", homophily: "#B77D22" };

const $ = (id) => document.getElementById(id);
const fmtInt = (x) => Math.round(x).toLocaleString("en-US");
const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
const fix = (x, d = 2) => Number(x).toFixed(d);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ error: "Bad response from server" }));
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}
let toastTimer;
function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), err ? 6000 : 3200);
}
function busy(btn, on, label) {
  if (on) { btn.dataset.label = btn.innerHTML; btn.innerHTML = `<span class="spinner"></span>${label || "Working…"}`; btn.disabled = true; }
  else { btn.innerHTML = btn.dataset.label || btn.innerHTML; btn.disabled = false; }
}
function lerpColor(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const r = Math.round(((pa >> 16) & 255) + (((pb >> 16) & 255) - ((pa >> 16) & 255)) * t);
  const g = Math.round(((pa >> 8) & 255) + (((pb >> 8) & 255) - ((pa >> 8) & 255)) * t);
  const bl = Math.round((pa & 255) + ((pb & 255) - (pa & 255)) * t);
  return `rgb(${r},${g},${bl})`;
}
function ramp(t) { // light -> gold -> red
  t = Math.max(0, Math.min(1, t));
  return t < 0.5 ? lerpColor("#DAD3DD", "#E2A33A", t / 0.5) : lerpColor("#E2A33A", "#B8342A", (t - 0.5) / 0.5);
}

// Chart.js defaults
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
const REM = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
Chart.defaults.font.size = Math.round(12.5 * REM() / 16 * 10) / 10;
Chart.defaults.color = C.ink2;
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.boxHeight = 12;
Chart.defaults.plugins.tooltip.backgroundColor = C.plum;
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.animation.duration = 700;

// Draws 95% CI whiskers on bar charts: dataset.ci = [[lo, hi], ...]
const ciPlugin = {
  id: "ciWhiskers",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((ds, di) => {
      if (!ds.ci) return;
      const meta = chart.getDatasetMeta(di);
      const y = chart.scales[meta.yAxisID];
      ctx.save();
      ctx.strokeStyle = C.plum; ctx.lineWidth = 1.5;
      meta.data.forEach((bar, i) => {
        const ci = ds.ci[i]; if (!ci) return;
        const x = bar.x, y1 = y.getPixelForValue(ci[0]), y2 = y.getPixelForValue(ci[1]);
        ctx.beginPath(); ctx.moveTo(x, y1); ctx.lineTo(x, y2);
        ctx.moveTo(x - 6, y1); ctx.lineTo(x + 6, y1); ctx.moveTo(x - 6, y2); ctx.lineTo(x + 6, y2);
        ctx.stroke();
      });
      ctx.restore();
    });
  },
};
// Writes values above bars
const valuePlugin = {
  id: "barValues",
  afterDatasetsDraw(chart, _, opts) {
    if (!opts || !opts.enabled) return;
    const { ctx } = chart;
    ctx.save();
    ctx.font = `700 ${Chart.defaults.font.size}px ${Chart.defaults.font.family}`;
    ctx.fillStyle = C.ink; ctx.textAlign = "center";
    chart.data.datasets.forEach((ds, di) => {
      const meta = chart.getDatasetMeta(di);
      if (meta.hidden) return;
      meta.data.forEach((bar, i) => {
        const v = ds.data[i]; if (v == null) return;
        const top = ds.ci && ds.ci[i] ? Math.min(bar.y, chart.scales[meta.yAxisID].getPixelForValue(ds.ci[i][1])) : bar.y;
        ctx.fillText(opts.format ? opts.format(v) : v, bar.x, top - 7);
      });
    });
    ctx.restore();
  },
};
Chart.register(ciPlugin, valuePlugin);

const charts = {};
function chart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), config);
  return charts[id];
}
const gridScale = (extra = {}) => ({ grid: { color: C.grid }, border: { display: false }, ...extra });

// keep the sticky header height available to CSS (used for canvas heights)
(() => {
  const bar = document.getElementById("appbar");
  const set = () => document.documentElement.style.setProperty("--appbar-h", bar.getBoundingClientRect().height + "px");
  new ResizeObserver(set).observe(bar);
  set();
  // chart text follows the root font size when the window is resized or the zoom changes
  let last = REM();
  window.addEventListener("resize", () => {
    const r = REM();
    if (Math.abs(r - last) < 0.2) return;
    last = r;
    Chart.defaults.font.size = Math.round(12.5 * r / 16 * 10) / 10;
    Object.values(charts).forEach((c) => c.update("none"));
  });
})();

// ------------------------------------------------------------------ app state
const S = { net: "cop26", tab: "overview", summary: null, layout: {}, det: {}, sim: {}, rendered: {} };

// ------------------------------------------------------------------ pipeline status
function stepIcon(st, i) {
  if (st === "done" || st === "cached") return "✓";
  if (st === "running") return "◌";
  if (st === "error") return "!";
  return i + 1;
}
function renderStepper(el, status, horizontal) {
  el.innerHTML = status.stages.map((s, i) => {
    const time = s.status === "cached" ? "cached" : (s.seconds != null ? `${fix(s.seconds, 1)} s` : "");
    return `<li class="${s.status}"><div class="ic">${stepIcon(s.status, i)}</div>
      <div><div class="t">${esc(s.label)}</div><div class="d">${esc(s.detail)}</div></div>
      ${horizontal ? `<div class="s">${time}</div>` : `<div class="s">${time}</div>`}</li>`;
  }).join("");
}
function setPill() { /* status pill removed from the header; progress shows on the loading screen */ }
async function pollStatus() {
  let st;
  try { st = await api("/api/status"); } catch (e) { setPill("error", "Server not reachable"); setTimeout(pollStatus, 1500); return; }
  if (st.state === "ready") {
    setPill("ready", st.from_cache ? "Ready · loaded from cache" : `Ready · computed in ${fix(st.total_seconds, 0)} s`);
    S.status = st;
    await onReady();
    return;
  }
  if (st.state === "error") {
    setPill("error", "Pipeline error");
    $("errorBox").textContent = st.error;
    $("errorBox").classList.remove("hidden");
    renderStepper($("stepperLoading"), st, false);
    return;
  }
  showLoading(true);
  const stages = st.stages || [];
  const idx = stages.findIndex((s) => s.status === "running");
  const done = stages.filter((s) => ["done", "cached"].includes(s.status)).length;
  const frac = stages.length ? (done + (idx >= 0 ? st.progress || 0 : 0)) / stages.length : 0;
  $("loadBar").style.width = `${Math.max(3, frac * 100)}%`;
  $("loadMsg").textContent = `${st.message || ""}  ·  ${fix(st.elapsed || 0, 0)} s elapsed`;
  if (stages.length) renderStepper($("stepperLoading"), st, false);
  setPill("running", idx >= 0 ? `Running ${done + 1}/${stages.length}` : "Starting…");
  setTimeout(pollStatus, 600);
}
function showLoading(on) {
  $("loading").classList.toggle("hidden", !on);
  document.querySelectorAll("#tabs button").forEach((b) => (b.disabled = on));
  if (on) document.querySelectorAll(".tab").forEach((t) => t.classList.add("hidden"));
}
async function onReady() {
  S.summary = await api("/api/summary");
  S.rendered = {};
  S.det = {};
  S.sim = {};
  showLoading(false);
  initControls();
  showTab(S.tab);
}

// ------------------------------------------------------------------ navigation
function showTab(tab) {
  S.tab = tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${tab}`));
  const key = `${tab}:${S.net}`;
  if (S.rendered[key]) { if (tab === "network" && S.graph) S.graph.resize(); if (tab === "playground" && S.pg) { S.pg.a.resize(); S.pg.b.resize(); } return; }
  S.rendered[key] = true;
  ({ overview: renderOverview, network: renderNetwork, detection: renderDetectionTab,
     simulation: renderSimulationTab, playground: renderPlayground, methods: renderMethods })[tab]();
}
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
document.querySelectorAll("#netSwitch button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.net === S.net || !S.summary) return;
  document.querySelectorAll("#netSwitch button").forEach((x) => x.classList.toggle("active", x === b));
  S.net = b.dataset.net;
  S.rendered = Object.fromEntries(Object.entries(S.rendered).filter(([k]) => k.startsWith("methods")));
  showTab(S.tab);
}));

const NETDATA = () => S.summary.networks[S.net];
const NETNAME = () => S.net.toUpperCase();

// ------------------------------------------------------------------ OVERVIEW
function renderOverview() {
  const N = NETDATA(), st = N.stats, m = S.summary.meta;
  $("ovTitle").textContent = `${N.label} retweet network`;
  $("integrity").innerHTML = m.md5_ok
    ? `<span class="ok">✓ Dataset verified</span><span>MD5 matches Zenodo</span><code>${m.md5.slice(0, 12)}…</code>`
    : `<span style="color:${C.bad};font-weight:700">! MD5 mismatch</span><code>${m.md5}</code>`;
  $("kpis").innerHTML = [
    { l: "Tweet records", v: fmtInt(st.records), s: `of ${fmtInt(m.rows)} in the release` },
    { l: "Posting accounts", v: fmtInt(st.accounts), s: `${fmtInt(S.summary.users_in_both)} active at both summits` },
    { l: "Retweet network", v: `${fmtInt(st.graph_nodes)}`, s: `accounts · ${fmtInt(st.graph_edges)} directed links`, accent: true },
    { l: "Flagged posts", v: pct(st.flagged_share), s: `${fmtInt(st.flagged_records)} posts, dataset classifier` },
  ].map((k) => `<div class="kpi${k.accent ? " accent" : ""}"><div class="label">${k.l}</div><div class="value">${k.v}</div><div class="sub">${k.s}</div></div>`).join("");

  const nets = ["cop26", "cop27"], nd = S.summary.networks;
  const barOpts = (title) => ({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, title: { display: true, text: title, color: C.plum, font: { weight: 650, size: 13 } },
      barValues: { enabled: true, format: (v) => v.toFixed(1) + "%" } },
    scales: { y: gridScale({ beginAtZero: true, suggestedMax: 16, ticks: { callback: (v) => v + "%" } }), x: { grid: { display: false } } },
  });
  chart("chFlag", { type: "bar", data: { labels: ["COP26", "COP27"], datasets: [{ data: nets.map((n) => nd[n].stats.flagged_share * 100),
    backgroundColor: nets.map((n) => (n === S.net ? C.plum6 : "#CDB9C8")), borderRadius: 6, maxBarThickness: 70 }] }, options: barOpts("Posts flagged") });
  chart("chCross", { type: "bar", data: { labels: ["COP26", "COP27"], datasets: [{ data: nets.map((n) => nd[n].stats.cross_community_share * 100),
    backgroundColor: nets.map((n) => (n === S.net ? C.gold : "#E8D3AE")), borderRadius: 6, maxBarThickness: 70 }] }, options: barOpts("Retweets crossing communities") });

  // findings
  const com = N.communities, det = N.detection, rep = N.reproduction.find((r) => Math.abs(r.p - 0.1) < 1e-9);
  const ranked = Object.entries(rep.strategies).filter(([k]) => k !== "random").sort((a, b) => b[1].reduction - a[1].reduction);
  const best = ranked[0], rnd = rep.strategies.random;
  $("findingsNet").textContent = NETNAME();
  $("findings").innerHTML = [
    [pct(1 - st.cross_community_share, 0), `of matched retweets stay <b>inside</b> their own community - only ${pct(st.cross_community_share)} cross between groups (echo chambers).`],
    [com.louvain_communities, `communities found by our Louvain run (modularity Q = ${fix(com.louvain_modularity)}), agreeing with the dataset's Infomap partition at NMI = ${fix(com.nmi_vs_infomap)}.`],
    [fix(det.metrics.roc_auc), `ROC-AUC for spotting spreader accounts from network behaviour alone (random guessing = 0.50; ${pct(det.counts.base_rate, 0)} of accounts are spreaders).`],
    [pct(best[1].reduction, 0), `less simulated spread when the top 1% of accounts by <b>${S.summary.strategies[best[0]].label.toLowerCase()}</b> are fact-checked (p = 10%). Random placement: ${pct(rnd.reduction)}.`, true],
  ].map(([big, txt, gold]) => `<li><div class="big${gold ? " gold" : ""}">${big}</div><p>${txt}</p></li>`).join("");

  renderStepper($("stepperDone"), S.status, true);
  $("pipeTotal").textContent = S.status.from_cache ? "Loaded from cache" : `Total ${fix(S.status.total_seconds, 0)} s`;
}
$("btnRerun").addEventListener("click", async () => {
  if (!confirmRerun()) return;
  try { await api("/api/rerun", {}); } catch (e) { toast(e.message, true); return; }
  S.summary = null; S.layout = {};
  showLoading(true);
  setTimeout(pollStatus, 400);
});
function confirmRerun() {
  const b = $("btnRerun");
  if (b.dataset.armed) { delete b.dataset.armed; b.textContent = "Re-run from raw data"; return true; }
  b.dataset.armed = "1"; b.textContent = "Click again to confirm (~1 min)";
  setTimeout(() => { if (b.dataset.armed) { delete b.dataset.armed; b.textContent = "Re-run from raw data"; } }, 4000);
  return false;
}

// ------------------------------------------------------------------ GRAPH VIEW (canvas)
class GraphView {
  constructor(canvas, opts = {}) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.opts = opts; this.nodes = []; this.edges = [];
    this.k = 1; this.tx = 0; this.ty = 0; this.showEdges = true; this.hover = -1;
    this.style = () => ({ fill: C.plum6, r: 3 });
    this.edgeHighlights = [];
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    if (opts.interactive) this.bindMouse();
  }
  setData(nodes, edges) {
    this.nodes = nodes; this.edges = edges;
    this.order = null; this.hover = -1; this.edgeHighlights = [];
    this.style = () => ({ fill: "#D9D2DB", r: 3 });
    this.resetView();
  }
  resize() {
    const r = this.cv.parentElement.getBoundingClientRect();
    if (!r.width) return;
    const dpr = window.devicePixelRatio || 1;
    this.w = r.width; this.h = r.height;
    this.cv.width = r.width * dpr; this.cv.height = r.height * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }
  resetView() { this.k = 1; this.tx = 0; this.ty = 0; this.draw(); }
  px(n) { // fill the canvas, allowing at most 1.5x stretch in one direction
    const m = Math.min(this.w, this.h), sx = Math.min(this.w * 0.94, m * 1.5), sy = Math.min(this.h * 0.92, m * 1.5);
    const ox = (this.w - sx) / 2, oy = (this.h - sy) / 2;
    return [(ox + n.x * sx) * this.k + this.tx, (oy + n.y * sy) * this.k + this.ty]; }
  draw() {
    if (!this.w) return;
    const ctx = this.ctx; ctx.clearRect(0, 0, this.w, this.h);
    const P = this.nodes.map((n) => this.px(n));
    this.P = P;
    if (this.showEdges && this.edges.length) {
      ctx.lineWidth = 0.6; ctx.strokeStyle = this.opts.edgeColor || "rgba(90,70,100,0.07)";
      ctx.beginPath();
      for (const [a, b] of this.edges) { ctx.moveTo(P[a][0], P[a][1]); ctx.lineTo(P[b][0], P[b][1]); }
      ctx.stroke();
    }
    if (this.hover >= 0 && this.adj) {
      ctx.lineWidth = 1.1; ctx.strokeStyle = "rgba(183,125,34,0.55)"; ctx.beginPath();
      for (const j of this.adj[this.hover]) { ctx.moveTo(P[this.hover][0], P[this.hover][1]); ctx.lineTo(P[j][0], P[j][1]); }
      ctx.stroke();
    }
    for (const h of this.edgeHighlights) {
      ctx.lineWidth = h.w || 1.6; ctx.strokeStyle = h.color; ctx.beginPath();
      for (const [a, b] of h.edges) { ctx.moveTo(P[a][0], P[a][1]); ctx.lineTo(P[b][0], P[b][1]); }
      ctx.stroke();
    }
    const scaleR = Math.min(2.2, Math.sqrt(this.k));
    const order = this.order || this.nodes.map((_, i) => i);
    for (const i of order) {
      const st = this.style(i); const [x, y] = P[i]; const r = st.r * scaleR;
      if (x < -20 || y < -20 || x > this.w + 20 || y > this.h + 20) continue;
      ctx.globalAlpha = st.alpha == null ? 1 : st.alpha;
      if (st.ring) { ctx.beginPath(); ctx.arc(x, y, r + 3.2, 0, 7); ctx.fillStyle = st.ring; ctx.fill();
        ctx.beginPath(); ctx.arc(x, y, r + 1.6, 0, 7); ctx.fillStyle = "#fff"; ctx.fill(); }
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fillStyle = st.fill; ctx.fill();
      if (st.stroke) { ctx.lineWidth = st.strokeW || 1; ctx.strokeStyle = st.stroke; ctx.stroke(); }
    }
    ctx.globalAlpha = 1;
    if (this.hover >= 0) { const [x, y] = P[this.hover]; ctx.beginPath(); ctx.arc(x, y, this.style(this.hover).r * scaleR + 4, 0, 7);
      ctx.lineWidth = 2; ctx.strokeStyle = C.plum; ctx.stroke(); }
  }
  bindMouse() {
    let drag = null;
    this.cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = this.cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const f = Math.exp(-e.deltaY * 0.0015), k2 = Math.min(12, Math.max(0.6, this.k * f)), g = k2 / this.k;
      this.tx = mx - (mx - this.tx) * g; this.ty = my - (my - this.ty) * g; this.k = k2; this.draw();
    }, { passive: false });
    this.cv.addEventListener("mousedown", (e) => { drag = { x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty }; });
    window.addEventListener("mouseup", () => (drag = null));
    this.cv.addEventListener("mousemove", (e) => {
      const r = this.cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      if (drag) { this.tx = drag.tx + e.clientX - drag.x; this.ty = drag.ty + e.clientY - drag.y; this.draw(); return; }
      let best = -1, bd = 14 * 14;
      if (this.P) this.P.forEach(([x, y], i) => { const d = (x - mx) ** 2 + (y - my) ** 2; if (d < bd) { bd = d; best = i; } });
      if (best !== this.hover) { this.hover = best; this.draw(); }
      if (this.opts.onHover) this.opts.onHover(best, mx, my);
    });
    this.cv.addEventListener("mouseleave", () => { this.hover = -1; this.draw(); if (this.opts.onHover) this.opts.onHover(-1); });
  }
}

// ------------------------------------------------------------------ NETWORK TAB
async function getLayout(net) {
  if (!S.layout[net]) S.layout[net] = await api(`/api/layout/${net}`);
  return S.layout[net];
}
function commColorMaps(nodes) {
  const maps = {};
  for (const key of ["louvain", "infomap"]) {
    const counts = {};
    nodes.forEach((n) => (counts[n[key]] = (counts[n[key]] || 0) + 1));
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, COMM_COLORS.length).map(([c]) => +c);
    maps[key] = Object.fromEntries(top.map((c, i) => [c, COMM_COLORS[i]]));
  }
  return maps;
}
function topFrac(nodes, key, frac) {
  const idx = nodes.map((_, i) => i).sort((a, b) => nodes[b][key] - nodes[a][key]);
  return new Set(idx.slice(0, Math.max(1, Math.ceil(nodes.length * frac))));
}

async function renderNetwork() {
  const N = NETDATA(), st = N.stats, com = N.communities;
  $("netLead").innerHTML = `${fmtInt(st.graph_nodes)} accounts and ${fmtInt(st.graph_edges)} directed retweet links (author → retweeter). ` +
    `Density ${st.density.toExponential(1)}, mean ${fix(st.mean_out_degree, 1)} retweeters per account, ${pct(st.largest_component / st.graph_nodes)} in one connected component.`;
  $("commKpis").innerHTML = [
    [com.louvain_communities, "Louvain communities"],
    [fix(com.louvain_modularity, 3), "Modularity Q"],
    [fix(com.nmi_vs_infomap, 3), "NMI vs Infomap"],
    [fix(com.ari_vs_infomap, 3), "ARI vs Infomap"],
    [pct(com.cross_share_louvain), "Cross-community retweets (Louvain)"],
    [pct(com.cross_share_infomap), "Cross-community retweets (Infomap)"],
  ].map(([v, l]) => `<div><b>${v}</b><span>${l}</span></div>`).join("");
  renderFlow(S.flowMode || "infomap");
  const colors = COMM_COLORS;
  $("commTable").innerHTML = `<tr><th>Community</th><th class="num">Accounts</th><th class="num">Share</th><th class="num">Internal links</th><th class="num">Avg flagged</th><th>Infomap match</th></tr>` +
    com.table.slice(0, 8).map((r) => `<tr><td><span class="swatch" style="background:${colors[r.community] || OTHER_COLOR}"></span>L${r.community}</td>
      <td class="num">${fmtInt(r.accounts)}</td><td class="num">${pct(r.share_of_graph)}</td><td class="num">${fmtInt(r.internal_edges)}</td>
      <td class="num">${pct(r.flagged_share)}</td><td>C${r.main_infomap} · ${pct(r.main_infomap_overlap, 0)}</td></tr>`).join("");
  renderTop(S.topMode || "degree");

  const L = await getLayout(S.net);
  $("sampleInfo").textContent = `${fmtInt(L.nodes.length)} of ${fmtInt(st.graph_nodes)} accounts, ${fmtInt(L.edges.length)} links`;
  if (!S.graph) {
    S.graph = new GraphView($("graphCanvas"), { interactive: true, onHover: showTip });
    ["colorBy", "sizeBy", "highlightBy"].forEach((id) => $(id).addEventListener("change", styleGraph));
    $("showEdges").addEventListener("change", (e) => { S.graph.showEdges = e.target.checked; S.graph.draw(); });
    $("btnResetView").addEventListener("click", () => S.graph.resetView());
  }
  S.graph.adj = L.nodes.map(() => []);
  L.edges.forEach(([a, b]) => { S.graph.adj[a].push(b); S.graph.adj[b].push(a); });
  S.graph.setData(L.nodes, L.edges);
  S.graph.resize();
  styleGraph();
}
function styleGraph() {
  const L = S.layout[S.net], nodes = L.nodes, g = S.graph;
  const colorBy = $("colorBy").value, sizeBy = $("sizeBy").value, hl = $("highlightBy").value;
  const maps = commColorMaps(nodes);
  const maxv = Math.max(...nodes.map((n) => n[sizeBy])) || 1;
  const hlSet = hl === "none" ? null : topFrac(nodes, hl, 0.03);
  g.order = nodes.map((_, i) => i).sort((a, b) => nodes[a][sizeBy] - nodes[b][sizeBy]);
  g.style = (i) => {
    const n = nodes[i];
    let fill;
    if (colorBy === "louvain" || colorBy === "infomap") fill = maps[colorBy][n[colorBy]] || OTHER_COLOR;
    else if (colorBy === "flag") fill = ramp(n.flag / 0.5);
    else fill = ramp(n.pred);
    const r = 2.2 + 10 * Math.sqrt(n[sizeBy] / maxv);
    if (hlSet) return hlSet.has(i) ? { fill, r: r + 1.5, ring: C.plum } : { fill, r, alpha: 0.28 };
    return { fill, r, alpha: 0.92 };
  };
  const lg = $("graphLegend");
  if (colorBy === "louvain" || colorBy === "infomap") {
    const pre = colorBy === "louvain" ? "L" : "C";
    lg.innerHTML = Object.entries(maps[colorBy]).map(([c, col]) => `<span><i class="dotc" style="background:${col}"></i>${pre}${c}</span>`).join("") +
      `<span><i class="dotc" style="background:${OTHER_COLOR}"></i>other</span>`;
  } else {
    const label = colorBy === "flag" ? "Flagged posts 0% → 50%+" : "Spreader probability 0 → 1";
    lg.innerHTML = `<span>${label}</span><span class="ramp" style="background:linear-gradient(90deg,${ramp(0)},${ramp(0.5)},${ramp(1)})"></span>`;
  }
  g.draw();
}
function showTip(i, x, y) {
  const tip = $("tooltip");
  if (i < 0) { tip.classList.add("hidden"); return; }
  const n = S.layout[S.net].nodes[i];
  tip.innerHTML = `<div class="id">${esc(n.id)}</div><table>
    <tr><td>Louvain / Infomap</td><td>L${n.louvain} / C${n.infomap}</td></tr>
    <tr><td>Retweeted by (out-degree)</td><td>${fmtInt(n.outdeg)}</td></tr>
    <tr><td>Retweets (in-degree)</td><td>${fmtInt(n.indeg)}</td></tr>
    <tr><td>Betweenness (sampled)</td><td>${fmtInt(n.btw)}</td></tr>
    <tr><td>PageRank × N</td><td>${fix(n.pr, 2)}</td></tr>
    <tr><td>Flagged posts</td><td>${pct(n.flag, 0)}</td></tr>
    <tr><td>Detector score</td><td>${fix(n.pred, 2)}</td></tr></table>`;
  tip.classList.remove("hidden");
  const wrap = $("graphWrap").getBoundingClientRect();
  tip.style.left = Math.min(x + 16, wrap.width - 230) + "px";
  tip.style.top = Math.min(y + 12, wrap.height - 190) + "px";
}
function renderFlow(mode) {
  S.flowMode = mode;
  document.querySelectorAll("#flowSwitch button").forEach((b) => b.classList.toggle("active", b.dataset.flow === mode));
  const f = NETDATA().communities[mode === "louvain" ? "flow_louvain" : "flow_infomap"];
  const M = f.matrix, k = M.length;
  let max = 1;
  M.forEach((r, i) => r.forEach((v, j) => { if (i !== j) max = Math.max(max, v); }));
  let html = `<table><tr><th>From \\ To</th>${f.labels.map((l) => `<th>${l}</th>`).join("")}</tr>`;
  for (let i = 0; i < k; i++) {
    html += `<tr><th>${f.labels[i]}</th>`;
    for (let j = 0; j < k; j++) {
      if (i === j) { html += `<td class="diag" title="${fmtInt(M[i][j])} within">within</td>`; continue; }
      const t = Math.sqrt(M[i][j] / max);
      const bg = lerpColor("#F6F1F4", "#3F2C47", t);
      html += `<td style="background:${bg};color:${t > 0.5 ? "#fff" : C.ink}">${fmtInt(M[i][j])}</td>`;
    }
    html += "</tr>";
  }
  $("flowMatrix").innerHTML = html + "</table>";
}
document.querySelectorAll("#flowSwitch button").forEach((b) => b.addEventListener("click", () => renderFlow(b.dataset.flow)));
function renderTop(mode) {
  S.topMode = mode;
  document.querySelectorAll("#topSwitch button").forEach((b) => b.classList.toggle("active", b.dataset.top === mode));
  const rows = NETDATA().top_accounts[mode];
  $("topTable").innerHTML = `<tr><th>Account</th><th class="num">Retweeters</th><th class="num">Betweenness</th><th class="num">PageRank</th><th>Comm.</th><th class="num">Flagged</th></tr>` +
    rows.map((r, i) => `<tr><td><code>${esc(r.id)}</code></td><td class="num">${fmtInt(r.outdeg)}</td><td class="num">${fmtInt(r.btw)}</td>
      <td class="num">${fix(r.pr, 1)}</td><td><span class="swatch" style="background:${COMM_COLORS[r.louvain] || OTHER_COLOR}"></span>L${r.louvain}</td><td class="num">${pct(r.flag, 0)}</td></tr>`).join("");
}
document.querySelectorAll("#topSwitch button").forEach((b) => b.addEventListener("click", () => renderTop(b.dataset.top)));

// ------------------------------------------------------------------ DETECTION TAB
let controlsReady = false;
function initControls() {
  if (controlsReady) return;
  controlsReady = true;
  $("detModel").innerHTML = Object.entries(S.summary.models).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("detShare").addEventListener("input", (e) => ($("detShareVal").textContent = e.target.value));
  $("detMin").addEventListener("input", (e) => ($("detMinVal").textContent = e.target.value));
  $("btnTrain").addEventListener("click", trainDetector);
  // simulation
  $("stratChecks").innerHTML = Object.entries(S.summary.strategies).map(([k, v]) =>
    `<label class="check" title="${esc(v.description)}"><input type="checkbox" class="strat" value="${k}" ${["random", "degree", "bridge"].includes(k) ? "checked" : ""}>
     <i class="sw" style="background:${STRAT_COLOR[k]};border-radius:3px"></i>${esc(v.label)}</label>`).join("");
  $("simP").addEventListener("input", (e) => ($("simPVal").textContent = e.target.value));
  $("simB").addEventListener("input", (e) => { $("simBVal").textContent = e.target.value; budgetHint(); });
  $("btnSim").addEventListener("click", runSim);
  $("btnSweep").addEventListener("click", runSweep);
  $("btnSlides").addEventListener("click", () => {
    $("simP").value = 10; $("simPVal").textContent = "10"; $("simB").value = 1; $("simBVal").textContent = "1";
    $("simSeeds").value = 10; $("simTrials").value = 200; $("simSeed").value = 0;
    document.querySelectorAll(".strat").forEach((c) => (c.checked = ["random", "degree", "bridge"].includes(c.value)));
    budgetHint(); runSim();
  });
  // playground
  $("pgStrategy").innerHTML = Object.entries(S.summary.strategies).filter(([k]) => k !== "random")
    .concat([["random", S.summary.strategies.random]])
    .map(([k, v]) => `<option value="${k}" ${k === "bridge" ? "selected" : ""}>${esc(v.label)}</option>`).join("");
  $("pgP").addEventListener("input", (e) => ($("pgPVal").textContent = e.target.value));
  $("pgB").addEventListener("input", (e) => ($("pgBVal").textContent = e.target.value));
  ["pgStrategy", "pgP", "pgB", "pgSeeds"].forEach((id) => $(id).addEventListener("change", () => loadCascade(false)));
  $("pgNew").addEventListener("click", () => { S.pgSeed = (S.pgSeed || 1) + 1; loadCascade(true); });
  $("pgPlay").addEventListener("click", togglePlay);
  $("pgStep").addEventListener("click", () => { stopPlay(); stepCascade(); });
  $("pgReset").addEventListener("click", () => { stopPlay(); resetCascade(); });
}

function renderDetectionTab() {
  const res = S.det[S.net] || NETDATA().detection;
  const s = res.settings;
  $("detModel").value = s.model;
  $("detShare").value = Math.round(s.share * 100); $("detShareVal").textContent = Math.round(s.share * 100);
  $("detMin").value = s.min_posts; $("detMinVal").textContent = s.min_posts;
  document.querySelectorAll(".detGroup").forEach((c) => (c.checked = s.groups.includes(c.value)));
  renderDetection(res);
}
async function trainDetector() {
  const btn = $("btnTrain");
  const groups = [...document.querySelectorAll(".detGroup:checked")].map((c) => c.value);
  if (!groups.length) { toast("Pick at least one feature group", true); return; }
  busy(btn, true, "Training…");
  try {
    const res = await api("/api/detect", { net: S.net, model: $("detModel").value, share: $("detShare").value / 100, min_posts: +$("detMin").value, groups });
    S.det[S.net] = res;
    S.layout[S.net] = null;  // refresh detector scores in the network view
    delete S.rendered[`network:${S.net}`]; delete S.rendered[`playground:${S.net}`];
    renderDetection(res);
    toast(`${res.settings.model_label}: ROC-AUC ${fix(res.metrics.roc_auc)} - the Detector strategy now uses this model`);
  } catch (e) { toast(e.message, true); }
  busy(btn, false);
}
function renderDetection(res) {
  const m = res.metrics, c = res.counts;
  $("detCounts").innerHTML = `${fmtInt(c.accounts)} accounts with ≥ ${res.settings.min_posts} posts · ${fmtInt(c.spreaders)} spreaders (${pct(c.base_rate)}) · train ${fmtInt(c.train)} / test ${fmtInt(c.test)}`;
  $("detKpis").innerHTML = [
    ["ROC-AUC", fix(m.roc_auc, 3), "0.5 = random", true], ["F1 score", fix(m.f1, 3), "spreader class"],
    ["Precision", pct(m.precision), "flagged that are right"], ["Recall", pct(m.recall), "spreaders caught"],
    ["Accuracy", pct(m.accuracy), `base rate ${pct(c.base_rate, 0)}`], ["Avg precision", fix(m.avg_precision, 3), `random ≈ ${fix(c.base_rate, 2)}`],
  ].map(([l, v, s, a]) => `<div class="kpi${a ? " accent" : ""}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");

  chart("chRoc", { type: "line", data: { datasets: [
      { label: `${res.settings.model_label} (AUC ${fix(m.roc_auc)})`, data: res.roc.fpr.map((x, i) => ({ x, y: res.roc.tpr[i] })), borderColor: C.plum6, backgroundColor: "rgba(122,73,102,.10)", fill: true, pointRadius: 0, borderWidth: 2.2, tension: 0 },
      { label: "Random guess", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: "#C9C1CC", borderDash: [5, 5], pointRadius: 0, borderWidth: 1.5 }] },
    options: { responsive: true, maintainAspectRatio: false, parsing: false,
      scales: { x: gridScale({ type: "linear", min: 0, max: 1, title: { display: true, text: "False positive rate" } }), y: gridScale({ min: 0, max: 1, title: { display: true, text: "True positive rate" } }) },
      plugins: { legend: { position: "bottom" } } } });

  const [[tn, fp], [fn, tp]] = res.confusion;
  const cell = (v, lbl, strong) => `<div class="c" style="background:${strong ? C.plum : "#F4EEF2"};color:${strong ? "#fff" : C.plum}"><b>${fmtInt(v)}</b><span>${lbl}</span></div>`;
  $("confusion").innerHTML = `<div></div><div class="h">Predicted normal</div><div class="h">Predicted spreader</div>
    <div class="h">Actual normal</div>${cell(tn, "true negatives", true)}${cell(fp, "false alarms", false)}
    <div class="h">Actual spreader</div>${cell(fn, "missed", false)}${cell(tp, "caught", true)}`;

  if (res.comparison) {
    chart("chCompare", { type: "bar", data: { labels: res.comparison.map((r) => r.label.replace(/ \+ /g, " +\n").split("\n")),
      datasets: [{ label: "ROC-AUC", data: res.comparison.map((r) => r.roc_auc), backgroundColor: [GROUP_COLOR.behaviour, GROUP_COLOR.structure, GROUP_COLOR.homophily], borderRadius: 6, maxBarThickness: 90 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, barValues: { enabled: true, format: (v) => v.toFixed(3) } },
        scales: { y: gridScale({ min: 0.5, max: 1, title: { display: true, text: "ROC-AUC (test set)" } }), x: { grid: { display: false } } } } });
  }
  if (res.importance) {
    const imp = res.importance.slice(0, 12);
    chart("chImportance", { type: "bar", data: { labels: imp.map((r) => r.label), datasets: [{ data: imp.map((r) => Math.max(0, r.value)),
      backgroundColor: imp.map((r) => GROUP_COLOR[r.group]), borderRadius: 4, maxBarThickness: 18 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `AUC drop ${c.raw.toFixed(4)} (${imp[c.dataIndex].group})` } } },
        scales: { x: gridScale({ beginAtZero: true }), y: { grid: { display: false }, ticks: { font: { size: 11.5 } } } } } });
  }
  $("suspectTable").innerHTML = `<tr><th>#</th><th>Account</th><th class="num">Model score</th><th class="num">Posts</th><th class="num">Flagged posts</th><th>Actually a spreader?</th></tr>` +
    res.top_test_accounts.map((r, i) => `<tr><td>${i + 1}</td><td><code>${esc(r.account)}</code></td><td class="num">${fix(r.score, 3)}<span class="bar-inline" style="width:${r.score * 60}px"></span></td>
      <td class="num">${fmtInt(r.posts)}</td><td class="num">${pct(r.flagged_share, 0)}</td><td>${r.is_spreader ? '<span class="tag yes">Yes</span>' : '<span class="tag no">No</span>'}</td></tr>`).join("");
}

// ------------------------------------------------------------------ SIMULATION TAB
function budgetHint() {
  const n = NETDATA().stats.graph_nodes;
  $("simBudgetN").textContent = `(${fmtInt(Math.ceil(($("simB").value / 100) * n))} of ${fmtInt(n)})`;
}
function simBody() {
  return { net: S.net, p: $("simP").value / 100, budget_pct: +$("simB").value, n_seeds: +$("simSeeds").value, trials: +$("simTrials").value,
    seed: +$("simSeed").value, strategies: [...document.querySelectorAll(".strat:checked")].map((c) => c.value) };
}
function renderSimulationTab() {
  budgetHint();
  renderRepro();
  const r = S.sim[S.net] || NETDATA().reproduction.find((x) => Math.abs(x.p - 0.1) < 1e-9);
  renderSim(r);
  if (S.sweep && S.sweep.network === S.net) renderSweep(S.sweep);
  else renderSweep({ network: S.net, points: NETDATA().reproduction, seconds: null });  // slide settings until a sweep is run
}
async function runSim() {
  const body = simBody();
  if (!body.strategies.length) { toast("Pick at least one strategy", true); return; }
  const btn = $("btnSim"); busy(btn, true, "Simulating…");
  try { const r = await api("/api/simulate", body); S.sim[S.net] = r; renderSim(r); }
  catch (e) { toast(e.message, true); }
  busy(btn, false);
}
function renderSim(r) {
  const names = Object.keys(r.strategies), sl = S.summary.strategies;
  $("simTitle").textContent = `Reduction in average reach · ${NETNAME()} · p = ${Math.round(r.p * 100)}%`;
  $("simMeta").textContent = `budget ${fmtInt(r.budget)} accounts (${r.budget_pct}%) · ${r.n_seeds} seeds · ${r.trials} paired trials${r.seconds ? ` · ${r.seconds} s` : ""}`;
  chart("chSim", { type: "bar", data: { labels: names.map((k) => sl[k].label), datasets: [{
      data: names.map((k) => r.strategies[k].reduction * 100), ci: names.map((k) => [r.strategies[k].ci_low * 100, r.strategies[k].ci_high * 100]),
      backgroundColor: names.map((k) => STRAT_COLOR[k]), borderRadius: 7, maxBarThickness: 84 }] },
    options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 22 } },
      plugins: { legend: { display: false }, barValues: { enabled: true, format: (v) => v.toFixed(1) + "%" },
        tooltip: { callbacks: { label: (c) => { const s = r.strategies[names[c.dataIndex]]; return [`Reduction ${pct(s.reduction)} (95% CI ${pct(s.ci_low)} – ${pct(s.ci_high)})`, `Mean reach ${fix(s.mean_reach, 1)} vs baseline ${fix(r.baseline_mean, 1)}`]; } } } },
      scales: { y: gridScale({ beginAtZero: true, suggestedMax: 70, ticks: { callback: (v) => v + "%" } }), x: { grid: { display: false } } } } });
  $("simTable").innerHTML = `<tr><th>Strategy</th><th class="num">Accounts fact-checked</th><th class="num">Mean reach</th><th class="num">Median reach</th><th class="num">Reduction</th><th class="num">95% CI</th></tr>
    <tr><td><span class="swatch" style="background:#E3DCE5"></span>No fact checks (baseline)</td><td class="num">0</td><td class="num">${fix(r.baseline_mean, 1)}</td><td class="num">${fix(r.baseline_median, 0)}</td><td class="num">-</td><td class="num">-</td></tr>` +
    names.map((k) => { const s = r.strategies[k]; return `<tr><td><span class="swatch" style="background:${STRAT_COLOR[k]}"></span>${sl[k].label}</td><td class="num">${fmtInt(r.budget)}</td>
      <td class="num">${fix(s.mean_reach, 1)}</td><td class="num">${fix(s.median_reach, 0)}</td><td class="num"><b>${pct(s.reduction)}</b></td><td class="num">${pct(s.ci_low)} – ${pct(s.ci_high)}</td></tr>`; }).join("");
  let txt = "";
  if (r.best_vs_second) {
    const b = r.best_vs_second, a = sl[b.best].label, c = sl[b.second].label;
    txt = b.significant
      ? `<b>${a}</b> beats <b>${c}</b> by ${fix(b.diff * 100, 1)} points (95% CI ${fix(b.ci_low * 100, 1)} to ${fix(b.ci_high * 100, 1)}) - a clear difference.`
      : `<b>${a}</b> and <b>${c}</b> are statistically tied: difference ${fix(b.diff * 100, 1)} points, 95% CI ${fix(b.ci_low * 100, 1)} to ${fix(b.ci_high * 100, 1)} includes zero.`;
  }
  if (r.strategies.random && names.length > 1) txt += ` Random placement: only ${pct(r.strategies.random.reduction)}.`;
  const ov = r.overlaps && r.overlaps["degree|bridge"];
  if (ov != null) txt += ` Degree and bridge share just ${ov} of ${r.budget} target accounts.`;
  $("simCallout").innerHTML = txt;
}
async function runSweep() {
  const body = simBody();
  if (!body.strategies.length) { toast("Pick at least one strategy", true); return; }
  body.ps = [0.02, 0.05, 0.1, 0.15, 0.2, 0.3];
  body.trials = Math.min(body.trials, 300);
  const btn = $("btnSweep"); busy(btn, true, "Sweeping…");
  try { const r = await api("/api/sweep", body); S.sweep = r; renderSweep(r); } catch (e) { toast(e.message, true); }
  busy(btn, false);
}
function renderSweep(r) {
  const sl = S.summary.strategies, pts = r.points, names = Object.keys(pts[0].strategies);
  $("sweepMeta").textContent = r.seconds == null ? `${NETNAME()} · slide settings · press "Sweep over p" for more points`
    : `${NETNAME()} · ${pts[0].trials} trials per point · ${r.seconds} s`;
  chart("chSweep", { type: "line", data: { labels: pts.map((p) => Math.round(p.p * 100) + "%"), datasets: names.map((k) => ({
      label: sl[k].label, data: pts.map((p) => p.strategies[k].reduction * 100), borderColor: STRAT_COLOR[k], backgroundColor: STRAT_COLOR[k],
      pointRadius: 4, pointHoverRadius: 6, borderWidth: 2.4, tension: 0.25 })) },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.raw.toFixed(1)}%` } } },
      scales: { y: gridScale({ beginAtZero: true, ticks: { callback: (v) => v + "%" }, title: { display: true, text: "Reduction in mean reach" } }),
        x: gridScale({ title: { display: true, text: "Spread probability p" } }) } } });
}
function renderRepro() {
  const rep = NETDATA().reproduction;
  let all = true;
  const rows = rep.map((r) => {
    const cells = ["random", "degree", "bridge"].map((k) => {
      const v = r.strategies[k].reduction * 100, s = r.slide[k], ok = Math.abs(v - s) < 0.006;
      all = all && ok;
      return `<td class="num">${v.toFixed(2)}% <span class="${ok ? "ok" : ""}" style="${ok ? "" : "color:" + C.bad}">${ok ? "✓" : "≠ " + s}</span></td>`;
    }).join("");
    const d = r.best_vs_second;
    return `<tr><td>p = ${Math.round(r.p * 100)}%</td>${cells}<td>${d && !d.significant ? '<span class="tag no">top two tied</span>' : `<span class="tag yes">${S.summary.strategies[d.best].label} clearly ahead</span>`}</td></tr>`;
  }).join("");
  $("reproTable").innerHTML = `<tr><th>Setting</th><th class="num">Random</th><th class="num">Degree</th><th class="num">Bridge</th><th>Verdict</th></tr>${rows}`;
  $("reproNote").innerHTML = all ? `<span class="ok">✓ All values match the presentation slides exactly.</span> They are recomputed from the raw data on every fresh run.` : "Some values differ from the slides.";
}

// ------------------------------------------------------------------ PLAYGROUND
async function renderPlayground() {
  const L = await getLayout(S.net);
  if (!S.pg) {
    const mk = (id) => new GraphView($(id), { interactive: false, edgeColor: "rgba(90,70,100,0.05)" });
    S.pg = { a: mk("pgCanvasA"), b: mk("pgCanvasB") };
  }
  S.pg.a.setData(L.nodes, L.edges); S.pg.b.setData(L.nodes, L.edges);
  S.pg.a.resize(); S.pg.b.resize();
  S.pgSeed = S.pgSeed || 1;
  await loadCascade(false);
}
async function loadCascade(autoplay) {
  stopPlay();
  try {
    S.cas = await api("/api/cascade", { net: S.net, strategy: $("pgStrategy").value, p: $("pgP").value / 100, budget_pct: +$("pgB").value, n_seeds: +$("pgSeeds").value, seed: S.pgSeed });
  } catch (e) { toast(e.message, true); return; }
  const L = S.layout[S.net];
  S.cas.edges = L.edges;
  S.cas.liveEdges = S.cas.live_edges.map((i) => L.edges[i]);
  S.cas.blocked = new Set(S.cas.targets);
  S.cas.seedSet = new Set(S.cas.seeds);
  $("pgTitleB").textContent = `With fact checks · ${S.summary.strategies[$("pgStrategy").value].label} (${S.cas.budget} accounts)`;
  resetCascade();
  if (autoplay) togglePlay();
}
function resetCascade() {
  const c = S.cas; if (!c) return;
  c.step = 0;
  c.stateA = new Int16Array(c.n).fill(-1); c.stateB = new Int16Array(c.n).fill(-1);
  applyWave(0);
  $("pgSummary").innerHTML = "Press <b>Play</b> to spread the claim.";
  $("pgPlay").textContent = "▶ Play";
}
function applyWave(k) {
  const c = S.cas;
  if (c.baseline[k]) c.baseline[k].forEach((i) => (c.stateA[i] = k));
  if (c.intervention[k]) c.intervention[k].forEach((i) => (c.stateB[i] = k));
  paintPanel(S.pg.a, c.stateA, false, k);
  paintPanel(S.pg.b, c.stateB, true, k);
  const ra = [...c.stateA].filter((v) => v >= 0).length, rb = [...c.stateB].filter((v) => v >= 0).length;
  $("pgCountA").textContent = `${ra} / ${c.n}`;
  $("pgCountB").textContent = `${rb} / ${c.n}`;
}
function paintPanel(view, state, withBlocks, k) {
  const c = S.cas;
  view.order = null;
  const reachedColor = (w) => lerpColor("#B77D22", "#E6B865", Math.min(1, w / 10));
  view.style = (i) => {
    const w = state[i], blocked = withBlocks && c.blocked.has(i);
    if (c.seedSet.has(i)) return { fill: "#C0392B", r: 6, ring: "#C0392B" };
    if (blocked) return { fill: C.plum, r: 5.2, ring: w >= 0 ? C.plum : "#9C8AA3", alpha: 1 };
    if (w >= 0) return { fill: reachedColor(w), r: w === k ? 5.4 : 4.2, alpha: 1 };
    return { fill: "#D9D2DB", r: 2.8, alpha: 0.9 };
  };
  // transmissions of the current wave
  const hl = [];
  if (k > 0) {
    for (const [a, b] of c.liveEdges) {
      if (state[b] === k && state[a] >= 0 && state[a] < k && !(withBlocks && c.blocked.has(a))) hl.push([a, b]);
    }
  }
  const older = [];
  for (const [a, b] of c.liveEdges) {
    if (state[b] >= 1 && state[b] < k && state[a] >= 0 && state[a] < state[b] && !(withBlocks && c.blocked.has(a))) older.push([a, b]);
  }
  view.edgeHighlights = [{ edges: older, color: "rgba(183,125,34,0.22)", w: 1 }, { edges: hl, color: "rgba(192,57,43,0.75)", w: 1.8 }];
  view.draw();
}
function stepCascade() {
  const c = S.cas; if (!c) return false;
  const maxK = Math.max(c.baseline.length, c.intervention.length) - 1;
  if (c.step >= maxK) { finishSummary(); return false; }
  c.step += 1;
  applyWave(c.step);
  if (c.step >= maxK) { finishSummary(); return false; }
  return true;
}
function finishSummary() {
  const c = S.cas, red = c.reach_baseline ? 1 - c.reach_intervention / c.reach_baseline : 0;
  $("pgSummary").innerHTML = `Without fact checks the claim reached <b>${c.reach_baseline}</b> accounts. Fact-checking <b>${c.budget}</b> accounts (${S.summary.strategies[$("pgStrategy").value].label}) held it to <b>${c.reach_intervention}</b> - <b>${pct(red, 0)}</b> less.`;
  $("pgPlay").textContent = "▶ Replay";
}
function togglePlay() {
  if (S.playTimer) { stopPlay(); return; }
  const c = S.cas; if (!c) return;
  const maxK = Math.max(c.baseline.length, c.intervention.length) - 1;
  if (c.step >= maxK) resetCascade();
  $("pgPlay").textContent = "❚❚ Pause";
  $("pgSummary").innerHTML = "Spreading the claim wave by wave…";
  S.playTimer = setInterval(() => { if (!stepCascade()) stopPlay(true); }, 850);
}
function stopPlay(finished) {
  if (S.playTimer) { clearInterval(S.playTimer); S.playTimer = null; }
  if (!finished && S.cas) $("pgPlay").textContent = "▶ Play";
}

// ------------------------------------------------------------------ METHODS
function renderMethods() {
  const s = S.summary.source;
  $("srcLinks").innerHTML = `Dataset: <a href="${s.zenodo}" target="_blank" rel="noopener">${s.zenodo}</a><br>Related paper: <a href="${s.paper}" target="_blank" rel="noopener">${s.paper}</a>`;
}

// ------------------------------------------------------------------ boot
pollStatus();
