const $ = (id) => document.getElementById(id);

const state = {
  symbol: "BTCUSDT",
  interval: "1h",
  chart: null,
  series: null,
  running: false,
};

function fmt(n, d = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const x = Number(n);
  if (Math.abs(x) >= 1000) return x.toLocaleString(undefined, { maximumFractionDigits: d });
  if (Math.abs(x) >= 1) return x.toFixed(d);
  return x.toPrecision(4);
}

function cls(n) {
  return Number(n) >= 0 ? "up" : "dn";
}

function toast(msg) {
  const el = $("toast");
  el.hidden = false;
  el.textContent = msg;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 4200);
}

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {
      detail = await res.text();
    }
    throw new Error(detail);
  }
  return res.json();
}

function tickClock() {
  $("clock").textContent = new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

function initChart() {
  const el = $("chart");
  state.chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "transparent" }, textColor: "#8b95a5" },
    grid: { vertLines: { color: "#1b2230" }, horzLines: { color: "#1b2230" } },
    rightPriceScale: { borderColor: "#232b36" },
    timeScale: { borderColor: "#232b36", timeVisible: true },
    crosshair: { mode: 0 },
    autoSize: true,
  });
  state.series = state.chart.addCandlestickSeries({
    upColor: "#0ecb81",
    downColor: "#f6465d",
    borderVisible: false,
    wickUpColor: "#0ecb81",
    wickDownColor: "#f6465d",
  });
}

async function loadConfig() {
  const cfg = await api("/api/config");
  const mode = (cfg.mode || "paper").toUpperCase();
  $("modePill").textContent = mode;
  $("modePill").classList.toggle("live", cfg.mode === "live");
  const feed = cfg.feed && cfg.feed !== "unknown" ? cfg.feed : "binance";
  $("enginePill").textContent = feed === "demo"
    ? "demo feed · native desk"
    : (cfg.engine || "native desk");
  if (feed === "demo") $("feedBanner").hidden = false;
}

async function loadMarkets() {
  const rows = await api("/api/markets");
  $("tape").innerHTML = rows.map((r) =>
    `<span><b>${r.symbol.replace("USDT", "")}</b> ${fmt(r.price)} <span class="${cls(r.change_pct)}">${r.change_pct >= 0 ? "+" : ""}${fmt(r.change_pct)}%</span></span>`
  ).join("");
  $("watchlist").innerHTML = rows.map((r) => `
    <div class="wrow ${r.symbol === state.symbol ? "on" : ""}" data-sym="${r.symbol}">
      <div class="s">${r.symbol.replace("USDT", "")}<span style="color:#8b95a5">USDT</span></div>
      <div class="p">${fmt(r.price)}</div>
      <div class="c ${cls(r.change_pct)}">${r.change_pct >= 0 ? "+" : ""}${fmt(r.change_pct)}%</div>
    </div>
  `).join("");
  $("watchlist").querySelectorAll(".wrow").forEach((row) => {
    row.addEventListener("click", () => selectSymbol(row.dataset.sym));
  });
}

async function loadChart() {
  const rows = await api(`/api/klines/${state.symbol}?interval=${state.interval}&limit=200`);
  const data = rows.map((c) => ({
    time: Math.floor(c.open_time / 1000),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
  state.series.setData(data);
  const last = rows[rows.length - 1];
  if (last) {
    $("symName").textContent = state.symbol;
    $("symPx").textContent = `${fmt(last.close, 4)} · ${state.interval}`;
  }
}

async function loadBook() {
  const book = await api(`/api/depth/${state.symbol}`);
  const n = Math.min(8, book.bids.length, book.asks.length);
  const rows = [];
  for (let i = 0; i < n; i += 1) {
    rows.push(`<div class="brow"><span class="up">${fmt(book.bids[i][0], 4)}</span><span class="dn">${fmt(book.asks[i][0], 4)}</span></div>`);
  }
  $("book").innerHTML = `<div class="brow"><span>BID</span><span>ASK</span></div>` + rows.join("");
  if (book.bids[0] && book.asks[0]) {
    const mid = (book.bids[0][0] + book.asks[0][0]) / 2;
    const spr = book.asks[0][0] - book.bids[0][0];
    $("spreadHint").textContent = `${fmt((spr / mid) * 10000, 2)} bps`;
  }
}

async function loadNews() {
  const data = await api("/api/news");
  const fg = data.fear_greed;
  $("fgHint").textContent = fg
    ? `Fear & Greed ${fg.value} · ${fg.classification}`
    : "Fear & Greed offline";
  $("news").innerHTML = (data.headlines || []).slice(0, 6).map((n) => `
    <div class="nitem">
      <div class="t">${n.title}</div>
      <div class="m">${n.source || "wire"}</div>
    </div>
  `).join("") || `<div class="nitem"><div class="t">No headlines.</div></div>`;
}

async function loadPortfolio() {
  const p = await api("/api/portfolio");
  $("equity").innerHTML = `${fmt(p.equity, 2)} <span class="${cls(p.pnl)}" style="font-size:14px">${p.pnl >= 0 ? "+" : ""}${fmt(p.pnl, 2)} (${fmt(p.pnl_pct, 2)}%)</span>`;
  $("positions").innerHTML = (p.positions || []).length
    ? p.positions.map((x) => `
      <div class="pos">
        <span>${x.symbol}</span>
        <span>${fmt(x.qty, 6)}</span>
        <span class="${cls(x.unrealized_pnl)}">${fmt(x.unrealized_pnl, 2)}</span>
      </div>`).join("")
    : `<div class="pos"><span>No open paper positions</span></div>`;
  $("orders").innerHTML = (p.orders || []).slice(0, 8).map((o) => `
    <div class="ord">
      <span>${o.side} ${o.symbol}</span>
      <span>${fmt(o.qty, 6)} @ ${fmt(o.price, 4)}</span>
      <span>${o.venue}</span>
    </div>
  `).join("");
}

function setPipeline(phase, kind) {
  document.querySelectorAll(".pipeline li").forEach((li) => {
    const order = ["market", "sentiment", "news", "structure", "debate", "plan", "trader", "risk", "pm"];
    const idx = order.indexOf(li.dataset.k);
    const cur = order.indexOf(phase);
    li.classList.toggle("on", idx <= cur);
    if (idx === cur && kind) {
      li.classList.toggle("good", kind === "good");
      li.classList.toggle("bad", kind === "bad");
    }
  });
}

function renderDecision(run) {
  const d = run.decision || {};
  const rating = d.rating || "Hold";
  $("rating").textContent = rating.toUpperCase();
  $("rating").className = "rating " + rating.toLowerCase();
  $("ratingSub").textContent = d.executive_summary || d.thesis || "";
  $("decisionMetrics").innerHTML = [
    ["Action", d.action],
    ["Size", `${((d.size_pct || 0) * 100).toFixed(1)}%`],
    ["Stop", fmt(d.stop_loss, 4)],
    ["Target", fmt(d.take_profit, 4)],
    ["Conf.", `${Math.round((d.confidence || 0) * 100)}%`],
    ["Engine", d.engine || "native"],
  ].map(([k, v]) => `<div class="metric"><span>${k}</span><b>${v ?? "—"}</b></div>`).join("");

  const reports = run.reports || [];
  $("reports").classList.remove("empty");
  $("reports").innerHTML = reports.map((r) => `
    <article class="rcard">
      <h3>${r.name} <span class="badge ${r.stance}">${r.stance}</span></h3>
      <p>${r.summary}</p>
    </article>
  `).join("");
  $("runMeta").textContent = `${run.symbol} · ${run.interval} · ${run.created_at?.slice(0, 19) || ""}`;
  setPipeline("pm", rating === "Buy" || rating === "Overweight" ? "good" : rating === "Hold" ? "" : "bad");
}

async function selectSymbol(sym) {
  state.symbol = sym;
  await Promise.all([loadMarkets(), loadChart(), loadBook()]);
}

async function runDesk() {
  if (state.running) return;
  state.running = true;
  $("analyzeBtn").disabled = true;
  $("analyzeBtn").textContent = "Agents working…";
  const steps = ["market", "sentiment", "news", "structure", "debate", "plan", "trader", "risk", "pm"];
  let i = 0;
  const pulse = setInterval(() => {
    setPipeline(steps[Math.min(i, steps.length - 1)]);
    i += 1;
  }, 280);
  try {
    const run = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        symbol: state.symbol,
        interval: state.interval,
        execute: $("autoExec").checked,
      }),
    });
    renderDecision(run);
    if (run.order) toast(`${run.order.side} filled ${run.order.qty} ${run.order.symbol} on ${run.order.venue}`);
    await loadPortfolio();
    await loadChart();
  } catch (err) {
    toast(err.message || String(err));
  } finally {
    clearInterval(pulse);
    state.running = false;
    $("analyzeBtn").disabled = false;
    $("analyzeBtn").textContent = "Run desk";
  }
}

function bind() {
  $("analyzeBtn").addEventListener("click", runDesk);
  $("resetBtn").addEventListener("click", async () => {
    await api("/api/portfolio/reset", { method: "POST" });
    await loadPortfolio();
    toast("Paper book reset to starting cash.");
  });
  $("intervals").querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      $("intervals").querySelectorAll("button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      state.interval = btn.dataset.tf;
      await loadChart();
    });
  });
}

async function boot() {
  tickClock();
  setInterval(tickClock, 1000);
  initChart();
  bind();
  try {
    await loadConfig();
    await Promise.all([loadMarkets(), loadChart(), loadBook(), loadNews(), loadPortfolio()]);
  } catch (err) {
    toast(err.message || String(err));
  }
  setInterval(() => {
    loadMarkets().catch(() => {});
    loadBook().catch(() => {});
    loadPortfolio().catch(() => {});
  }, 15000);
}

boot();
