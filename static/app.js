const $ = (id) => document.getElementById(id);
const state = {
  status: null,
  symbol: "BTCUSDT",
  market: null,
  portfolio: null,
  runs: [],
  latestResult: null,
  offline: false,
  polling: false,
};

const assets = {
  BTC: { name: "Bitcoin", mark: "₿" },
  ETH: { name: "Ethereum", mark: "Ξ" },
  SOL: { name: "Solana", mark: "S" },
  XRP: { name: "XRP", mark: "X" },
  ADA: { name: "Cardano", mark: "A" },
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let payload;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
  return payload;
}

function money(value, maximumFractionDigits = 2) {
  if (!Number.isFinite(Number(value))) return "$—";
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits,
  }).format(value);
}

function price(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const digits = number >= 1000 ? 2 : number >= 1 ? 3 : 6;
  return money(number, digits);
}

function compact(value) {
  if (!Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function toast(message, kind = "info") {
  const element = document.createElement("div");
  element.className = `toast ${kind}`;
  element.textContent = message;
  $("toastStack").appendChild(element);
  window.setTimeout(() => element.remove(), 4800);
}

function fallbackStatus() {
  return {
    mode: "preview", intelligence: "Dashboard preview", broker_connected: false,
    execution_enabled: false, auto_trading_enabled: false, auto_execute: false,
    interval_minutes: 60, symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    quote_asset: "USDT", risk_per_trade_pct: 1, max_position_pct: 15,
    min_confidence: 62, stop_loss_pct: 2, take_profit_pct: 4,
    safety_message: "Backend offline — no orders can be placed",
  };
}

function fallbackMarket(symbol) {
  const quote = state.status?.quote_asset || "USDT";
  const base = symbol.replace(new RegExp(`${quote}$`), "");
  const anchors = { BTC: 64280, ETH: 3420, SOL: 172.4 };
  const anchor = anchors[base] || 100;
  const candles = Array.from({ length: 80 }, (_, index) => {
    const wave = Math.sin(index / 6) * .007 + Math.sin(index / 17) * .012;
    const close = anchor * (1 + wave + index * .00018);
    return { open_time: Date.now() - (80 - index) * 3600000, open: close * .998, high: close * 1.003, low: close * .997, close, volume: 1000 };
  });
  const current = candles.at(-1).close;
  return {
    symbol, price: current, change_24h_pct: 1.28, high_24h: current * 1.014,
    low_24h: current * .982, rsi_14: 58.4, sma_20: current * .994,
    sma_50: current * .987, volatility_pct: 2.31, data_source: "synthetic",
    candles,
  };
}

async function initialize() {
  bindEvents();
  try {
    state.status = await api("/api/status");
  } catch (error) {
    state.offline = true;
    state.status = fallbackStatus();
    toast("Backend is offline. Showing a read-only dashboard preview.", "error");
  }
  state.symbol = state.status.symbols[0];
  renderStatus();
  renderSymbolTabs();
  await Promise.all([loadPortfolio(), loadRuns(), loadMarket(state.symbol)]);
}

function renderStatus() {
  const status = state.status;
  $("modePill").textContent = status.mode.toUpperCase();
  $("intelligencePill").innerHTML = `<span class="pulse-dot ${status.broker_connected ? "" : "muted"}"></span>${escapeHtml(status.intelligence)}`;
  $("safetyMessage").textContent = status.safety_message;
  $("quoteAssetLabel").textContent = `${status.quote_asset} settlement balance`;
  $("readinessValue").textContent = status.broker_connected ? "Operational" : "Read only";
  $("readinessLabel").textContent = status.broker_connected ? status.intelligence : "Backend connection required";
  $("automationDot").classList.toggle("muted", !status.auto_trading_enabled);
  $("automationLabel").textContent = status.auto_trading_enabled ? "Scheduler active" : "Manual cycles";
  $("automationSchedule").textContent = status.auto_trading_enabled ? `Every ${status.interval_minutes} minutes` : "No unattended analysis";
  $("executeHelp").textContent = status.mode === "paper" ? "Simulated in paper mode" : status.mode === "testnet" ? "Routes to Spot Testnet" : "Requires explicit confirmation";
  $("executeToggle").disabled = !status.execution_enabled;
  $("riskBudget").textContent = `${status.risk_per_trade_pct.toFixed(1)}%`;
  $("positionCap").textContent = `${status.max_position_pct.toFixed(1)}%`;
  $("confidenceGate").textContent = `${status.min_confidence.toFixed(0)}%`;
  document.querySelectorAll(".risk-item .mini-track i")[0].style.width = `${Math.min(100, status.risk_per_trade_pct * 20)}%`;
  document.querySelectorAll(".risk-item .mini-track i")[1].style.width = `${status.max_position_pct}%`;
  document.querySelectorAll(".risk-item .mini-track i")[2].style.width = `${status.min_confidence}%`;
}

function renderSymbolTabs() {
  const quote = state.status.quote_asset;
  $("symbolTabs").innerHTML = state.status.symbols.map((symbol) => {
    const base = symbol.replace(new RegExp(`${quote}$`), "");
    return `<button type="button" data-symbol="${escapeHtml(symbol)}" class="${symbol === state.symbol ? "active" : ""}">${escapeHtml(base)}</button>`;
  }).join("");
}

async function selectSymbol(symbol) {
  if (state.polling) return;
  state.symbol = symbol;
  renderSymbolTabs();
  await loadMarket(symbol);
  const matchingRun = state.runs.find((run) => run.symbol === symbol && run.status === "completed" && run.result);
  if (matchingRun) renderDecision(matchingRun.result);
  else clearDecision();
}

async function loadMarket(symbol) {
  $("chartLoading").classList.remove("hidden");
  try {
    state.market = state.offline ? fallbackMarket(symbol) : await api(`/api/market/${encodeURIComponent(symbol)}`);
  } catch (error) {
    state.market = fallbackMarket(symbol);
    toast(`${error.message}. Showing a synthetic chart; execution remains governed by the backend.`, "error");
  }
  renderMarket();
}

function renderMarket() {
  const market = state.market;
  const quote = state.status.quote_asset;
  const base = market.symbol.replace(new RegExp(`${quote}$`), "");
  const asset = assets[base] || { name: base, mark: base[0] };
  $("assetLogo").textContent = asset.mark;
  $("assetPair").textContent = `${base} / ${quote}`;
  $("assetName").textContent = `${asset.name} · Spot market`;
  $("marketPrice").textContent = price(market.price);
  const change = Number(market.change_24h_pct);
  $("marketChange").textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
  $("marketChange").classList.toggle("negative", change < 0);
  $("marketHigh").textContent = price(market.high_24h);
  $("marketLow").textContent = price(market.low_24h);
  $("marketRsi").textContent = Number(market.rsi_14).toFixed(1);
  $("sma20").textContent = price(market.sma_20);
  $("sma50").textContent = price(market.sma_50);
  $("volatility").textContent = `${Number(market.volatility_pct).toFixed(2)}%`;
  $("dataSource").textContent = market.data_source;
  $("dataSource").style.color = market.data_source === "binance" ? "var(--green)" : "var(--amber)";
  $("chartLoading").classList.add("hidden");
  drawChart(market.candles || []);
}

function drawChart(candles) {
  const canvas = $("priceChart");
  const container = canvas.parentElement;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(container.clientWidth - 24, 300);
  const height = Math.max(container.clientHeight - 4, 180);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  const values = candles.slice(-72).map((candle) => Number(candle.close));
  if (values.length < 2) return;
  const padding = { top: 14, right: 55, bottom: 24, left: 7 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const point = (value, index) => ({
    x: padding.left + (index / (values.length - 1)) * plotWidth,
    y: padding.top + ((max - value) / range) * plotHeight,
  });

  context.lineWidth = 1;
  context.strokeStyle = "#1d252a";
  context.fillStyle = "#5d696f";
  context.font = "9px system-ui";
  context.textAlign = "right";
  for (let index = 0; index < 4; index += 1) {
    const y = padding.top + (index / 3) * plotHeight;
    context.beginPath(); context.moveTo(padding.left, y); context.lineTo(width - padding.right + 5, y); context.stroke();
    const label = max - (index / 3) * range;
    context.fillText(label >= 1000 ? label.toFixed(0) : label.toFixed(2), width - 3, y + 3);
  }

  context.beginPath();
  values.forEach((value, index) => {
    const p = point(value, index);
    if (index === 0) context.moveTo(p.x, p.y); else context.lineTo(p.x, p.y);
  });
  const last = point(values.at(-1), values.length - 1);
  context.lineTo(last.x, height - padding.bottom);
  context.lineTo(padding.left, height - padding.bottom);
  context.closePath();
  context.fillStyle = "rgba(201, 242, 107, .055)";
  context.fill();

  context.beginPath();
  values.forEach((value, index) => {
    const p = point(value, index);
    if (index === 0) context.moveTo(p.x, p.y); else context.lineTo(p.x, p.y);
  });
  context.strokeStyle = "#c9f26b";
  context.lineWidth = 1.65;
  context.stroke();
  context.beginPath(); context.arc(last.x, last.y, 3.1, 0, Math.PI * 2); context.fillStyle = "#c9f26b"; context.fill();
  context.beginPath(); context.arc(last.x, last.y, 6.5, 0, Math.PI * 2); context.strokeStyle = "rgba(201,242,107,.25)"; context.stroke();
}

async function loadPortfolio() {
  if (state.offline) {
    state.portfolio = { total_equity: 10000, available_cash: 10000, invested_value: 0, recent_orders: [] };
  } else {
    try { state.portfolio = await api("/api/portfolio"); }
    catch (error) { toast(`Portfolio unavailable: ${error.message}`, "error"); return; }
  }
  const p = state.portfolio;
  $("totalEquity").textContent = money(p.total_equity);
  $("availableCash").textContent = money(p.available_cash);
  $("investedValue").textContent = money(p.invested_value);
  const exposure = p.total_equity ? p.invested_value / p.total_equity * 100 : 0;
  $("exposureLabel").textContent = `${exposure.toFixed(1)}% portfolio exposure`;
}

async function loadRuns() {
  if (state.offline) { renderActivity(); return; }
  try { state.runs = await api("/api/runs?limit=12"); }
  catch (error) { toast(`Activity unavailable: ${error.message}`, "error"); return; }
  renderActivity();
  const latest = state.runs.find((run) => run.symbol === state.symbol && run.status === "completed" && run.result);
  if (latest) renderDecision(latest.result);
}

function renderActivity() {
  if (!state.runs.length) {
    $("activityList").innerHTML = '<div class="activity-empty">No agent cycles recorded yet.</div>';
    return;
  }
  $("activityList").innerHTML = state.runs.slice(0, 8).map((run) => {
    const rating = run.result?.analysis?.rating || "—";
    const action = run.result?.plan?.action || (run.execute_requested ? "Pending" : "Analysis");
    const timestamp = new Date(run.created_at);
    return `<div class="activity-row">
      <span class="activity-icon">${run.status === "completed" ? "✓" : run.status === "failed" ? "!" : "••"}</span>
      <div class="activity-main"><strong>${escapeHtml(run.symbol)} · ${escapeHtml(action)}</strong><small>${escapeHtml(run.stage)}</small></div>
      <div class="activity-cell">${escapeHtml(rating)}<small>RATING</small></div>
      <div class="activity-cell">${run.execute_requested ? "Enabled" : "Off"}<small>EXECUTION</small></div>
      <div class="activity-cell">${timestamp.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}<small>STARTED</small></div>
      <span class="activity-status ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
    </div>`;
  }).join("");
}

function clearDecision() {
  state.latestResult = null;
  $("decisionEmpty").classList.remove("hidden");
  $("decisionContent").classList.add("hidden");
  $("openReportButton").disabled = true;
  $("stopLevel").textContent = "—";
  $("takeLevel").textContent = "—";
  $("planReason").textContent = "Risk limits are applied after agent consensus and before every order.";
}

function renderDecision(result) {
  state.latestResult = result;
  const analysis = result.analysis;
  const plan = result.plan;
  $("decisionEmpty").classList.add("hidden");
  $("decisionContent").classList.remove("hidden");
  $("openReportButton").disabled = false;
  $("decisionRating").textContent = analysis.rating.toUpperCase();
  $("decisionRating").className = `decision-badge ${analysis.rating.toLowerCase()}`;
  $("confidenceValue").textContent = `${Math.round(analysis.confidence)}%`;
  $("confidenceRing").style.borderColor = analysis.confidence >= state.status.min_confidence ? "var(--lime)" : "var(--amber)";
  $("decisionSummary").textContent = analysis.summary;
  $("planAction").textContent = plan.action;
  $("planAction").style.color = plan.action === "BUY" ? "var(--green)" : plan.action === "SELL" ? "var(--red)" : "var(--amber)";
  $("planNotional").textContent = money(plan.notional);
  $("planEntry").textContent = price(plan.entry_price);
  $("stopLevel").textContent = plan.stop_loss ? price(plan.stop_loss) : "—";
  $("takeLevel").textContent = plan.take_profit ? price(plan.take_profit) : "—";
  $("planReason").textContent = plan.reason;
  $("agentSourceBadge").textContent = analysis.source === "tradingagents" ? "AI CONSENSUS" : "DEMO LOGIC";
}

async function runAgent() {
  if (state.offline) { toast("Start the FastAPI backend to run an agent cycle.", "error"); return; }
  const execute = $("executeToggle").checked;
  let confirmation = null;
  if (execute && state.status.mode === "live") {
    const expected = `EXECUTE ${state.symbol}`;
    confirmation = window.prompt(`Live order safety check. Type exactly: ${expected}`);
    if (confirmation !== expected) { toast("Live execution cancelled: phrase did not match.", "error"); return; }
  }
  const headers = {};
  if (state.status.control_auth_required) {
    let token = window.sessionStorage.getItem("northstar-control-token");
    if (!token) token = window.prompt("Enter the operator control token for this session:");
    if (!token) { toast("A control token is required.", "error"); return; }
    window.sessionStorage.setItem("northstar-control-token", token);
    headers["X-Control-Token"] = token;
  }
  setRunning(true);
  try {
    const run = await api("/api/runs", {
      method: "POST",
      headers,
      body: JSON.stringify({ symbol: state.symbol, execute, confirmation }),
    });
    await pollRun(run.id);
  } catch (error) {
    if (error.message.toLowerCase().includes("control token")) {
      window.sessionStorage.removeItem("northstar-control-token");
    }
    toast(error.message, "error");
    setRunning(false);
  }
}

async function pollRun(runId) {
  let elapsed = 0;
  const timer = window.setInterval(() => {
    elapsed += 1;
    $("runTimer").textContent = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;
  }, 1000);
  try {
    while (true) {
      const run = await api(`/api/runs/${runId}`);
      updateProgress(run.stage);
      if (run.status === "completed") {
        renderDecision(run.result);
        toast(run.result.order ? `${run.result.order.side} order filled in ${run.result.order.mode} mode.` : "Agent cycle completed. No order was submitted.");
        break;
      }
      if (run.status === "failed") throw new Error(run.error || "Agent cycle failed");
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    await Promise.all([loadRuns(), loadPortfolio(), loadMarket(state.symbol)]);
  } catch (error) {
    toast(error.message, "error");
    await loadRuns();
  } finally {
    window.clearInterval(timer);
    setRunning(false);
  }
}

function setRunning(running) {
  state.polling = running;
  $("runAgentButton").disabled = running;
  $("runAgentButton").querySelector("span").textContent = running ? "Agents are working…" : "Run agent cycle";
  $("runProgress").classList.toggle("hidden", !running);
  if (!running) {
    document.querySelectorAll(".agent-node").forEach((node) => node.classList.remove("active", "complete"));
    $("progressBar").style.width = "0";
  }
}

function updateProgress(stage) {
  $("runStage").textContent = stage;
  const lower = stage.toLowerCase();
  let index = 0;
  if (lower.includes("analyst")) index = 1;
  if (lower.includes("risk")) index = 2;
  if (lower.includes("validat") || lower.includes("execut")) index = 3;
  if (lower.includes("complete")) index = 4;
  const nodes = [...document.querySelectorAll(".agent-node")];
  nodes.forEach((node, nodeIndex) => {
    node.classList.toggle("complete", nodeIndex < index);
    node.classList.toggle("active", nodeIndex === Math.min(index, 3));
  });
  $("progressBar").style.width = `${Math.max(10, (index + 1) * 22)}%`;
}

function openReport() {
  const reports = state.latestResult?.analysis?.reports;
  if (!reports) return;
  const entries = Object.entries(reports).filter(([, value]) => value);
  $("reportTitle").textContent = `${state.symbol} agent report`;
  $("reportTabs").innerHTML = entries.map(([key], index) => `<button type="button" data-report="${escapeHtml(key)}" class="${index === 0 ? "active" : ""}">${escapeHtml(key.replaceAll("_", " "))}</button>`).join("");
  $("reportBody").textContent = entries[0]?.[1] || "No report content.";
  $("reportDrawer").classList.add("open");
  $("reportDrawer").setAttribute("aria-hidden", "false");
  $("drawerBackdrop").classList.remove("hidden");
}

function closeReport() {
  $("reportDrawer").classList.remove("open");
  $("reportDrawer").setAttribute("aria-hidden", "true");
  $("drawerBackdrop").classList.add("hidden");
}

function bindEvents() {
  $("symbolTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-symbol]");
    if (button) selectSymbol(button.dataset.symbol);
  });
  $("runAgentButton").addEventListener("click", runAgent);
  $("refreshButton").addEventListener("click", async () => {
    await Promise.all([loadMarket(state.symbol), loadPortfolio(), loadRuns()]);
    toast("Dashboard refreshed.");
  });
  $("refreshActivity").addEventListener("click", loadRuns);
  $("openReportButton").addEventListener("click", openReport);
  $("closeReportButton").addEventListener("click", closeReport);
  $("drawerBackdrop").addEventListener("click", closeReport);
  $("reportTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-report]");
    if (!button) return;
    document.querySelectorAll("#reportTabs button").forEach((item) => item.classList.toggle("active", item === button));
    $("reportBody").textContent = state.latestResult.analysis.reports[button.dataset.report] || "No report content.";
  });
  $("mobileMenu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
  document.querySelectorAll("[data-scroll]").forEach((button) => button.addEventListener("click", () => {
    $(button.dataset.scroll)?.scrollIntoView({ behavior: "smooth", block: "start" });
    document.querySelector(".sidebar").classList.remove("open");
  }));
  window.addEventListener("resize", () => { if (state.market) drawChart(state.market.candles || []); });
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeReport(); });
}

document.addEventListener("DOMContentLoaded", initialize);
