"use strict";

// Apartment prices by district and big city over time (CBS data), and mortgage rates (BOI).
// Reads data/data.json (built by `python -m apartment_data.export.web`) and draws a map with a
// time slider, a ranking table, a line chart, a heatmap and a rates chart with ECharts.

const MAX_COMPARE = 8;
const PALETTE = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    sequential: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    diverging: ["#184f95", "#6da7ec", "#f0efec", "#ef8f8e", "#b8302f"],
    index: "#898781",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    sequential: ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
    diverging: ["#6da7ec", "#256abf", "#383835", "#c24a49", "#ef8f8e"],
    index: "#898781",
  },
};
const ROOM_LABELS = {
  all: "כל הדירות",
  "1-2": "1–2 חדרים",
  "2.5-3": "2.5–3 חדרים",
  "3.5-4": "3.5–4 חדרים",
  "4.5-5": "4.5–5 חדרים",
  "4.5-6": "4.5 חדרים ומעלה",
  "5.5-6": "5.5–6 חדרים",
};

const SMOOTH_QUARTERS = 4;

// Mortgage tracks for the payment view: rate series and their share of the loan.
const TRACKS = {
  mix: { label: "תמהיל: שליש פריים, שליש קבועה, שליש צמודה", parts: [["prime", 1 / 3], ["mortgage_fixed_unindexed", 1 / 3], ["mortgage_fixed_cpi", 1 / 3]] },
  mortgage_fixed_unindexed: { label: "קבועה לא צמודה", parts: [["mortgage_fixed_unindexed", 1]] },
  prime: { label: "פריים (ריבית הפריים)", parts: [["prime", 1]] },
  mortgage_fixed_cpi: { label: "קבועה צמודה למדד", parts: [["mortgage_fixed_cpi", 1]] },
  mortgage_variable_cpi: { label: "משתנה צמודה למדד", parts: [["mortgage_variable_cpi", 1]] },
};
const RATE_LABELS = {
  mortgage_fixed_unindexed: "קבועה לא צמודה",
  mortgage_fixed_cpi: "קבועה צמודה",
  mortgage_variable_cpi: "משתנה צמודה",
  prime: "ריבית הפריים",
  boi_rate: "ריבית בנק ישראל",
};
const DEFAULT_LTV = 70;
const DEFAULT_YEARS = 25;
const MAX_LTV = 75; // Bank of Israel cap for a first home
const CALC_DEFAULTS = { income: 20000, equity: 600000, pti: 30, years: 25, track: "mix", rooms: "all" };

// One sentence on what the current kind means, for readers new to the terms.
const EXPLAIN = {
  sale: 'מחיר ממוצע של הדירות שנמכרו בפועל ברבעון, לפי הלמ"ס. זה ממוצע ולא מדד: אם ברבעון נמכרו יותר דירות גדולות, הממוצע עולה גם בלי שהמחירים עלו.',
  rent: 'שכר הדירה החודשי הממוצע, לפי סקר שכר הדירה של הלמ"ס.',
  ratio: "כמה שנים של שכר דירה שווה דירה: המחיר הממוצע חלקי שכר הדירה השנתי הממוצע. יחס גבוה אומר שקנייה יקרה ביחס לשכירות.",
  payment: "ההחזר החודשי ההתחלתי על משכנתא לדירה במחיר ממוצע, לפי הריבית הממוצעת באותו רבעון. את המסלול, אחוז המימון והתקופה משנים בשדות למעלה.",
};
const THEMES = { auto: "אוטומטית", light: "בהירה", dark: "כהה" };

const state = {
  kind: "sale", // 'sale', 'rent', 'ratio' (price / yearly rent) or 'payment' (monthly mortgage)
  rooms: "all",
  real: "nominal",
  mode: "price",
  smooth: false,
  track: "mix",
  ltv: DEFAULT_LTV,
  years: DEFAULT_YEARS,
  base: 0,
  t: 0,
  tab: "map",
  place: null, // place shown in the side panel
  calc: { ...CALC_DEFAULTS },
  selected: [],
  slots: {}, // place id -> palette slot; colour follows the place, not its position
};

let DATA = null;
let PLACES = {};
const charts = {};
let playTimer = null;
let heatRows = [];

// ---------- helpers ----------

const $ = (sel) => document.querySelector(sel);

function theme() {
  const forced = document.documentElement.dataset.theme;
  if (forced) return forced;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ink() {
  const css = getComputedStyle($(".viz-root"));
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    primary: v("--text-primary"),
    secondary: v("--text-secondary"),
    muted: v("--text-muted"),
    grid: v("--grid"),
    axis: v("--axis"),
    surface: v("--surface-1"),
  };
}

function quarterLabel(iso) {
  const [y, m] = iso.split("-").map(Number);
  return `רבעון ${Math.floor((m - 1) / 3) + 1} ${y}`;
}

function shortQuarter(iso) {
  const [y, m] = iso.split("-").map(Number);
  return `Q${Math.floor((m - 1) / 3) + 1} ${y}`;
}

const nf0 = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function formatValue(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (state.mode === "change") return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
  if (state.kind === "sale") return `${nf2.format(v / 1e6)} מיליון ₪`;
  if (state.kind === "ratio") return `${v.toFixed(1)} שנים`;
  return `${nf0.format(v)} ₪`;
}

function money(v) {
  return v == null || Number.isNaN(v) ? "—" : `${nf0.format(Math.round(v))} ₪`;
}

function millions(v) {
  return v == null || Number.isNaN(v) ? "—" : `${nf2.format(v / 1e6)} מיליון ₪`;
}

function formatRate(v) {
  return v == null || Number.isNaN(v) ? "—" : `${v.toFixed(2)}%`;
}

function formatAxis(v) {
  if (state.mode === "change") return `${Math.round(v)}%`;
  if (state.kind === "sale") return `${(v / 1e6).toFixed(1)}M`;
  if (state.kind === "ratio") return `${Math.round(v)}`;
  return nf0.format(v);
}

function valueName() {
  if (state.kind === "sale") return "מחיר ממוצע";
  if (state.kind === "rent") return "שכר דירה ממוצע";
  if (state.kind === "payment") return "החזר חודשי";
  return "שנות שכירות";
}

function formatPercent(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

// Kinds that are computed from the sale price use its rooms groups and deal counts.
function saleBased() {
  return state.kind === "sale" || state.kind === "payment";
}

function cell(placeId, kind = saleBased() ? "sale" : state.kind) {
  return DATA.series[kind]?.[placeId]?.[state.rooms];
}

function rawPrice(kind, placeId, i) {
  const raw = cell(placeId, kind)?.price?.[i];
  if (raw == null) return null;
  if (state.real === "real") {
    const f = DATA.real_factor[i];
    return f == null ? null : raw * f;
  }
  return raw;
}

// Monthly payment of an annuity (Spitzer) loan.
function annuity(principal, annualRatePct, years) {
  const n = years * 12;
  const r = annualRatePct / 100 / 12;
  if (Math.abs(r) < 1e-9) return principal / n;
  return (principal * r) / (1 - (1 + r) ** -n);
}

// Opening monthly payment per 1 NIS of loan in quarter i, or null without rates.
function loanFactor(track, years, i) {
  let total = 0;
  for (const [code, share] of TRACKS[track].parts) {
    const rate = DATA.rates?.quarterly?.[code]?.[i];
    if (rate == null) return null;
    total += annuity(share, rate, years);
  }
  return total;
}

// Opening monthly payment on a loan of LTV % of the average price, at the quarter's rates.
function payment(placeId, i) {
  const sale = rawPrice("sale", placeId, i);
  const f = loanFactor(state.track, state.years, i);
  return sale == null || f == null ? null : ((sale * state.ltv) / 100) * f;
}

// Nominal published value, independent of the view options.
function published(kind, placeId, rooms, i) {
  return DATA.series[kind]?.[placeId]?.[rooms]?.price?.[i] ?? null;
}

function lastIndex(kind, placeId, rooms = "all") {
  for (let i = DATA.periods.length - 1; i >= 0; i--) {
    if (published(kind, placeId, rooms, i) != null) return i;
  }
  return -1;
}

function firstIndex(kind, placeId, rooms = "all") {
  return DATA.periods.findIndex((_, i) => published(kind, placeId, rooms, i) != null);
}

function pctChange(now, then) {
  return now == null || then == null || then === 0 ? null : (now / then - 1) * 100;
}

function signed(v) {
  return v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function trendClass(v) {
  return v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
}

// The level shown before the change transform: a price in NIS (nominal or real), for
// 'ratio' the years of rent a dwelling costs (sale price / yearly rent), and for 'payment'
// the monthly mortgage payment in NIS.
function level(placeId, i) {
  if (state.kind === "payment") return payment(placeId, i);
  if (state.kind !== "ratio") return rawPrice(state.kind, placeId, i);
  const sale = rawPrice("sale", placeId, i);
  const rent = rawPrice("rent", placeId, i);
  return sale == null || rent == null || rent === 0 ? null : sale / (rent * 12);
}

// Level at period i, optionally as the mean of the last SMOOTH_QUARTERS quarters.
function price(placeId, i) {
  if (!state.smooth) return level(placeId, i);
  if (i < SMOOTH_QUARTERS - 1) return null;
  let sum = 0;
  for (let k = i - SMOOTH_QUARTERS + 1; k <= i; k++) {
    const v = level(placeId, k);
    if (v == null) return null;
    sum += v;
  }
  return sum / SMOOTH_QUARTERS;
}

function changeSince(placeId, i, base) {
  const now = price(placeId, i);
  const then = price(placeId, base);
  if (now == null || then == null || then === 0) return null;
  return (now / then - 1) * 100;
}

// The value the views show: a price, or the change in % since the base quarter.
function value(placeId, i) {
  return state.mode === "change" ? changeSince(placeId, i, state.base) : price(placeId, i);
}

function deals(placeId, i) {
  return saleBased() ? (cell(placeId)?.deals?.[i] ?? null) : null;
}

function placesWithData() {
  return DATA.places.filter((p) => DATA.periods.some((_, i) => price(p.id, i) != null));
}

function roomsFor(kind) {
  if (kind === "payment") kind = "sale";
  if (kind !== "ratio") return DATA.rooms[kind] || ["all"];
  const rent = new Set(DATA.rooms.rent || []);
  return (DATA.rooms.sale || []).filter((r) => rent.has(r));
}

// One fixed colour scale over every quarter, so colours stay comparable while time moves.
function valueRange(places) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of places) {
    for (let i = 0; i < DATA.periods.length; i++) {
      const v = value(p.id, i);
      if (v == null) continue;
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  if (!Number.isFinite(lo)) return [0, 1];
  if (state.mode === "change") {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
    return [-m, m];
  }
  return [lo, hi];
}

function visualMap(range, extra) {
  const pal = PALETTE[theme()];
  const c = ink();
  return {
    type: "continuous",
    min: range[0],
    max: range[1],
    calculable: false,
    realtime: true,
    inRange: { color: state.mode === "change" ? pal.diverging : pal.sequential },
    text: [formatAxis(range[1]), formatAxis(range[0])],
    textStyle: { color: c.secondary },
    formatter: (v) => formatAxis(v),
    ...extra,
  };
}

function placeLabel(p) {
  return p.name;
}

// ---------- controls ----------

function setSegment(key, val) {
  state[key] = val;
  document.querySelectorAll(`.segmented[data-key="${key}"] button`).forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.value === val));
  });
}

function fillRooms() {
  const select = $("#rooms");
  const rooms = roomsFor(state.kind);
  if (!rooms.includes(state.rooms)) state.rooms = "all";
  select.innerHTML = rooms
    .map((r) => `<option value="${r}"${r === state.rooms ? " selected" : ""}>${ROOM_LABELS[r] || r}</option>`)
    .join("");
}

function fillTrack() {
  $("#track").innerHTML = Object.entries(TRACKS)
    .map(([k, t]) => `<option value="${k}"${k === state.track ? " selected" : ""}>${t.label}</option>`)
    .join("");
  $("#ltv").value = state.ltv;
  $("#years").value = state.years;
}

function clampInput(el, lo, hi, fallback) {
  const v = Number(el.value);
  return Number.isFinite(v) && v >= lo && v <= hi ? v : fallback;
}

function fillBase() {
  const select = $("#base");
  select.innerHTML = DATA.periods
    .map((p, i) => `<option value="${i}"${i === state.base ? " selected" : ""}>${quarterLabel(p)}</option>`)
    .join("");
  $("#base-control").hidden = state.mode !== "change";
}

function bindControls() {
  document.querySelectorAll(".segmented").forEach((group) => {
    group.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      setSegment(group.dataset.key, btn.dataset.value);
      if (group.dataset.key === "kind") fillRooms();
      syncControls();
      render();
    });
  });
  $("#smooth").addEventListener("change", (e) => {
    state.smooth = e.target.checked;
    render();
  });
  $("#share").addEventListener("click", shareLink);
  $("#download").addEventListener("click", downloadCsv);
  $("#track").addEventListener("change", (e) => {
    state.track = e.target.value;
    render();
  });
  $("#ltv").addEventListener("input", (e) => {
    state.ltv = clampInput(e.target, 1, 100, state.ltv);
    render();
  });
  $("#years").addEventListener("input", (e) => {
    state.years = clampInput(e.target, 1, 40, state.years);
    render();
  });
  $("#rooms").addEventListener("change", (e) => {
    state.rooms = e.target.value;
    render();
  });
  $("#base").addEventListener("change", (e) => {
    state.base = Number(e.target.value);
    render();
  });
  $("#time").addEventListener("input", (e) => {
    state.t = Number(e.target.value);
    renderMap();
    renderRanking();
  });
  $("#play").addEventListener("click", togglePlay);
  document.querySelectorAll(".tabs button").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
}

// Show only the controls that matter for the current choices.
function syncControls() {
  $("#base-control").hidden = state.mode !== "change";
  // Real prices cancel out in a ratio of two prices.
  $("#real-control").hidden = state.kind === "ratio";
  document.querySelectorAll(".payment-control").forEach((el) => {
    el.hidden = state.kind !== "payment";
  });
  $(".controls").classList.toggle("own-tab", state.tab === "rates" || state.tab === "calc");
  $("#smooth").checked = state.smooth;
  renderExplain();
}

function renderExplain() {
  let text = EXPLAIN[state.kind] || "";
  if (state.real === "real" && state.kind !== "ratio") {
    text += " במחירים ריאליים הסכומים מתואמים לאינפלציה, בשקלים של הרבעון האחרון.";
  }
  if (state.mode === "change") text += " מוצג השינוי באחוזים מאז הרבעון שנבחר.";
  $("#explain").textContent = text;
}

function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  });
  for (const name of ["map", "line", "heat", "rates", "calc"]) {
    $(`#panel-${name}`).hidden = name !== tab;
  }
  syncControls();
  render();
}

function togglePlay() {
  if (playTimer) {
    stopPlay();
    return;
  }
  if (state.t >= DATA.periods.length - 1) state.t = 0;
  $("#play").textContent = "❚❚";
  $("#play").setAttribute("aria-label", "עצירה");
  playTimer = setInterval(() => {
    if (state.t >= DATA.periods.length - 1) {
      stopPlay();
      return;
    }
    state.t += 1;
    $("#time").value = state.t;
    renderMap();
    renderRanking();
  }, 800);
}

function stopPlay() {
  clearInterval(playTimer);
  playTimer = null;
  $("#play").textContent = "▶";
  $("#play").setAttribute("aria-label", "הפעלה");
}

// ---------- map ----------

function renderMap() {
  const chart = charts.map;
  const c = ink();
  const i = state.t;
  $("#time-label").textContent = quarterLabel(DATA.periods[i]);
  const places = placesWithData();
  const range = valueRange(places);
  const districts = places
    .filter((p) => p.level === "district")
    .map((p) => ({ name: p.id, value: value(p.id, i) }));
  const cities = places
    .filter((p) => p.level === "city" && p.lat != null)
    .map((p) => ({ name: p.id, value: [p.lon, p.lat, value(p.id, i)] }));

  const tooltip = (params) => {
    const id = params.name;
    const p = PLACES[id];
    if (!p) return "";
    const lines = [`<strong>${placeLabel(p)}</strong>`, `${quarterLabel(DATA.periods[i])}: ${formatValue(value(id, i))}`];
    if (state.mode === "price") {
      lines.push(`שינוי מ${quarterLabel(DATA.periods[state.base])}: ${formatPercent(changeSince(id, i, state.base))}`);
    }
    const d = deals(id, i);
    if (d != null) lines.push(`${nf0.format(d)} עסקאות`);
    return lines.join("<br>");
  };

  chart.setOption(
    {
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: tooltip, confine: true },
      visualMap: visualMap(range, {
        left: "left",
        bottom: 10,
        itemHeight: 140,
        seriesIndex: [0, 1],
      }),
      geo: {
        map: "il",
        roam: true,
        nameProperty: "name",
        aspectScale: 0.85,
        layoutCenter: ["50%", "50%"],
        layoutSize: "95%",
        scaleLimit: { min: 1, max: 8 },
        itemStyle: { areaColor: c.grid, borderColor: c.surface, borderWidth: 1.5 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: null, borderColor: c.primary, borderWidth: 2 } },
        select: { disabled: true },
        label: { show: false },
      },
      series: [
        {
          type: "map",
          geoIndex: 0,
          data: districts,
        },
        {
          type: "scatter",
          coordinateSystem: "geo",
          data: cities,
          symbolSize: (v, params) => {
            const pop = PLACES[params.name]?.population || 100000;
            return Math.max(9, Math.min(22, Math.sqrt(pop) / 30));
          },
          itemStyle: { borderColor: c.surface, borderWidth: 2 },
          emphasis: { scale: 1.3, label: { show: true } },
          label: {
            show: false,
            formatter: (p) => PLACES[p.name]?.name || "",
            position: "left",
            color: c.primary,
            fontSize: 12,
          },
          zlevel: 1,
        },
      ],
    },
    { replaceMerge: ["series"] },
  );
}

// ---------- ranking table ----------

function renderRanking() {
  const i = state.t;
  const rows = placesWithData()
    .map((p) => ({ p, v: value(p.id, i), ch: changeSince(p.id, i, state.base), d: deals(p.id, i) }))
    .sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity));
  $("#rank-title").textContent = `דירוג, ${quarterLabel(DATA.periods[i])}`;
  $("#rank-value-head").textContent =
    state.mode === "change" ? `שינוי מ${shortQuarter(DATA.periods[state.base])}` : valueName();
  $("#rank-change-head").textContent = state.mode === "change" ? valueName() : `שינוי מ${shortQuarter(DATA.periods[state.base])}`;
  $("#rank-deals-head").hidden = !saleBased();
  $("#rank-body").innerHTML = rows
    .map(({ p, v, ch, d }) => {
      const second = state.mode === "change" ? formatPriceOnly(price(p.id, i)) : formatPercent(ch);
      const cls = ch == null ? "" : ch > 0 ? "up" : ch < 0 ? "down" : "";
      return `<tr class="level-${p.level}" data-id="${p.id}" tabindex="0"><td>${placeLabel(p)}</td><td class="num">${formatValue(v)}</td>` +
        `<td class="num ${state.mode === "change" ? "" : cls}">${second}</td>` +
        (saleBased() ? `<td class="num">${d == null ? "—" : nf0.format(d)}</td>` : "") +
        "</tr>";
    })
    .join("");
}

function formatPriceOnly(v) {
  const mode = state.mode;
  state.mode = "price";
  const s = formatValue(v);
  state.mode = mode;
  return s;
}

// ---------- picker + line chart ----------

function slotFor(id) {
  if (state.slots[id] != null) return state.slots[id];
  const used = new Set(Object.values(state.slots));
  for (let s = 0; s < MAX_COMPARE; s++) {
    if (!used.has(s)) {
      state.slots[id] = s;
      return s;
    }
  }
  return 0;
}

function toggleSelected(id) {
  const at = state.selected.indexOf(id);
  if (at >= 0) {
    state.selected.splice(at, 1);
    delete state.slots[id];
  } else if (state.selected.length < MAX_COMPARE) {
    state.selected.push(id);
    slotFor(id);
  }
  renderPicker();
  renderLine();
}

function renderPicker() {
  const pal = PALETTE[theme()].series;
  const groups = [
    ["", DATA.places.filter((p) => p.level === "national")],
    ["מחוזות", DATA.places.filter((p) => p.level === "district")],
    ["ערים גדולות", DATA.places.filter((p) => p.level === "city")],
  ];
  const full = state.selected.length >= MAX_COMPARE;
  $("#picker").innerHTML = groups
    .map(([label, list]) => {
      const head = label ? `<span class="group-label">${label}</span>` : "";
      const chips = list
        .map((p) => {
          const on = state.selected.includes(p.id);
          const colour = on ? pal[state.slots[p.id]] : "transparent";
          return `<button type="button" class="chip" data-id="${p.id}" aria-pressed="${on}"${!on && full ? " disabled" : ""}>` +
            `<span class="swatch" style="background:${colour}"></span>${p.name}</button>`;
        })
        .join("");
      return head + chips;
    })
    .join("");
  $("#picker").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => toggleSelected(b.dataset.id)));
}

// The CBS quality-adjusted index, as % change since the base quarter (real when prices are).
function indexLine() {
  const idx = DATA.indices["40010"];
  if (!idx || state.mode !== "change" || state.kind !== "sale") return null;
  const adjusted = idx.values.map((v, i) => {
    if (v == null || state.real !== "real") return v;
    const f = DATA.real_factor[i];
    return f == null ? null : v * f;
  });
  const base = adjusted[state.base];
  if (base == null) return null;
  return adjusted.map((v) => (v == null ? null : (v / base - 1) * 100));
}

function renderLine() {
  const chart = charts.line;
  const c = ink();
  const pal = PALETTE[theme()];
  const labels = DATA.periods.map(shortQuarter);
  const last = DATA.periods.length - 1;
  const series = state.selected.map((id) => {
    const p = PLACES[id];
    const data = DATA.periods.map((_, i) => value(id, i));
    return {
      name: p.name,
      type: "line",
      data,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2 },
      itemStyle: { color: pal.series[state.slots[id]] },
      endLabel: state.selected.length <= 4 ? { show: true, formatter: "{a}", color: c.secondary, fontSize: 12 } : undefined,
      labelLayout: { moveOverlap: "shiftY" },
      emphasis: { focus: "series" },
    };
  });
  const idx = indexLine();
  if (idx) {
    series.push({
      name: "מדד מחירי הדירות (כלל הארץ)",
      type: "line",
      data: idx,
      showSymbol: false,
      lineStyle: { width: 2, type: "dashed", color: pal.index },
      itemStyle: { color: pal.index },
    });
  }
  if (series.length) {
    series[0].markArea = {
      silent: true,
      itemStyle: { color: theme() === "dark" ? "rgba(255,255,255,0.05)" : "rgba(11,11,11,0.04)" },
      label: { show: true, position: "insideTop", color: c.muted, fontSize: 11, formatter: "ארעי" },
      data: [[{ xAxis: labels[last - 1] }, { xAxis: labels[last] }]],
    };
  }

  chart.setOption(
    {
      backgroundColor: "transparent",
      grid: { left: 64, right: state.selected.length <= 4 ? 120 : 24, top: 40, bottom: 48 },
      legend: { top: 0, textStyle: { color: c.secondary }, itemWidth: 18, itemHeight: 8, icon: "roundRect" },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: c.axis } },
        valueFormatter: (v) => formatValue(v),
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: c.axis } },
        axisLabel: { color: c.muted, interval: 3 },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: state.mode === "price",
        axisLabel: { color: c.muted, formatter: formatAxis },
        splitLine: { lineStyle: { color: c.grid } },
      },
      series,
    },
    { notMerge: true },
  );
}

// ---------- heatmap ----------

function renderHeat() {
  const chart = charts.heat;
  const c = ink();
  const places = placesWithData();
  const rows = places.slice().reverse(); // first place on top
  heatRows = rows;
  const data = [];
  rows.forEach((p, y) => {
    DATA.periods.forEach((_, x) => {
      const v = value(p.id, x);
      if (v != null) data.push([x, y, v]);
    });
  });
  const range = valueRange(places);
  chart.setOption(
    {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params) => {
          const [x, y, v] = params.value;
          const p = rows[y];
          const d = deals(p.id, x);
          return `<strong>${p.name}</strong><br>${quarterLabel(DATA.periods[x])}: ${formatValue(v)}` +
            (d != null ? `<br>${nf0.format(d)} עסקאות` : "");
        },
      },
      grid: { left: 110, right: 16, top: 16, bottom: 90 },
      xAxis: {
        type: "category",
        data: DATA.periods.map(shortQuarter),
        axisLabel: { color: c.muted, interval: 3 },
        axisLine: { lineStyle: { color: c.axis } },
        axisTick: { show: false },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: rows.map((p) => p.name),
        axisLabel: { color: c.secondary },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      visualMap: visualMap(range, { orient: "horizontal", left: "center", bottom: 10, itemWidth: 12, itemHeight: 200 }),
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 2 },
          emphasis: { itemStyle: { borderColor: c.primary, borderWidth: 1 } },
        },
      ],
    },
    { notMerge: true },
  );
}

// ---------- rates ----------

function renderRates() {
  const chart = charts.rates;
  const c = ink();
  const pal = PALETTE[theme()];
  const rates = DATA.rates;
  const labels = rates.months.map((m) => {
    const [y, mo] = m.split("-");
    return `${mo}/${y}`;
  });
  let slot = 0;
  const series = Object.entries(rates.series).map(([code, s]) => {
    const policy = code === "boi_rate";
    const colour = policy ? pal.index : pal.series[slot++];
    return {
      name: RATE_LABELS[code] || s.name,
      type: "line",
      data: s.values,
      showSymbol: false,
      step: code === "prime" || policy ? "end" : undefined,
      lineStyle: { width: 2, type: policy ? "dashed" : "solid", color: colour },
      itemStyle: { color: colour },
      emphasis: { focus: "series" },
    };
  });
  chart.setOption(
    {
      backgroundColor: "transparent",
      // The legend wraps to two rows on a narrow screen.
      grid: { left: 48, right: 24, top: chart.getWidth() < 600 ? 64 : 40, bottom: 48 },
      legend: { top: 0, textStyle: { color: c.secondary }, itemWidth: 18, itemHeight: 8, icon: "roundRect" },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: c.axis } },
        valueFormatter: formatRate,
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: c.axis } },
        axisLabel: { color: c.muted, interval: (i, v) => v.startsWith("01/") && Number(v.slice(3)) % 2 === 0, formatter: (v) => v.slice(3) },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: c.muted, formatter: (v) => `${v}%` },
        splitLine: { lineStyle: { color: c.grid } },
      },
      series,
    },
    { notMerge: true },
  );
}

// ---------- headline cards ----------

function kpiCard(label, value, sub) {
  return `<div class="kpi"><p class="kpi-label">${label}</p><p class="kpi-value">${value}</p><p class="kpi-sub">${sub}</p></div>`;
}

// Fixed headline numbers for the whole country, independent of the view options.
function renderKpis() {
  const cards = [];
  const i = lastIndex("sale", "n0");
  if (i >= 0) {
    const now = published("sale", "n0", "all", i);
    cards.push(kpiCard("מחיר דירה ממוצע בישראל", millions(now), quarterLabel(DATA.periods[i])));
    if (i >= 4) {
      const then = published("sale", "n0", "all", i - 4);
      const yoy = pctChange(now, then);
      const f = DATA.real_factor;
      const real = f[i] != null && f[i - 4] != null ? pctChange(now * f[i], then * f[i - 4]) : null;
      cards.push(
        kpiCard(
          "שינוי במחיר בשנה האחרונה",
          `<span class="${trendClass(yoy)}">${signed(yoy)}</span>`,
          `לעומת ${quarterLabel(DATA.periods[i - 4])}` + (real != null ? ` · ריאלי ${signed(real)}` : ""),
        ),
      );
    }
  }
  const prime = DATA.rates?.series?.prime?.values;
  if (prime) {
    let k = prime.length - 1;
    while (k >= 0 && prime[k] == null) k--;
    if (k >= 0) {
      const [y, m] = DATA.rates.months[k].split("-");
      const ago = k >= 12 ? prime[k - 12] : null;
      cards.push(kpiCard("ריבית הפריים", formatRate(prime[k]), `${m}/${y}` + (ago != null ? ` · לפני שנה ${formatRate(ago)}` : "")));
    }
  }
  for (let j = i; j >= 0; j--) {
    const f = loanFactor("mix", DEFAULT_YEARS, j);
    const price = published("sale", "n0", "all", j);
    if (f == null || price == null) continue;
    cards.push(
      kpiCard(
        "החזר חודשי על דירה ממוצעת",
        money((price * DEFAULT_LTV) / 100 * f),
        `${DEFAULT_LTV}% מימון, ${DEFAULT_YEARS} שנה, תמהיל · ${quarterLabel(DATA.periods[j])}`,
      ),
    );
    break;
  }
  $("#kpis").innerHTML = cards.join("");
}

// ---------- place panel ----------

function districtName(p) {
  return p.district ? PLACES[p.district]?.name : null;
}

function openPlace(id) {
  if (!PLACES[id]) return;
  const wasOpen = state.place != null;
  state.place = id;
  $("#place-panel").hidden = false;
  if (!charts.place) charts.place = echarts.init($("#pp-chart"));
  renderPlace();
  charts.place.resize();
  writeHash();
  if (!wasOpen) $("#pp-close").focus();
}

function closePlace() {
  state.place = null;
  $("#place-panel").hidden = true;
  writeHash();
}

function ppStat(label, value, sub = "") {
  return `<div class="pp-stat"><p class="kpi-label">${label}</p><p class="kpi-value">${value}</p>${sub ? `<p class="kpi-sub">${sub}</p>` : ""}</div>`;
}

function renderPlace() {
  const id = state.place;
  const p = PLACES[id];
  if (!p) return;
  $("#pp-title").textContent = p.name;
  const sub = [];
  if (p.level === "city") {
    if (districtName(p)) sub.push(districtName(p));
    if (p.population) sub.push(`${nf0.format(p.population)} תושבים`);
  } else if (p.level === "district") {
    sub.push("מחוז");
  } else {
    sub.push("ממוצע ארצי");
  }
  $("#pp-sub").textContent = sub.join(" · ");

  const i = lastIndex("sale", id);
  const stats = [];
  if (i >= 0) {
    const price = published("sale", id, "all", i);
    stats.push(ppStat("מחיר ממוצע", millions(price), quarterLabel(DATA.periods[i])));
    const yoy = i >= 4 ? pctChange(price, published("sale", id, "all", i - 4)) : null;
    stats.push(ppStat("שינוי בשנה", `<span class="${trendClass(yoy)}">${signed(yoy)}</span>`, i >= 4 ? `לעומת ${quarterLabel(DATA.periods[i - 4])}` : ""));
    const first = firstIndex("sale", id);
    const since = pctChange(price, published("sale", id, "all", first));
    stats.push(ppStat("שינוי מאז תחילת הנתונים", `<span class="${trendClass(since)}">${signed(since)}</span>`, `מאז ${quarterLabel(DATA.periods[first])}`));
    // Rank among places of the same level in the same quarter.
    const peers = DATA.places
      .filter((q) => q.level === p.level && published("sale", q.id, "all", i) != null)
      .sort((a, b) => published("sale", b.id, "all", i) - published("sale", a.id, "all", i));
    if (peers.length > 1) {
      const kindName = p.level === "city" ? "ערים" : "מחוזות";
      stats.push(ppStat("דירוג המחיר", `${peers.findIndex((q) => q.id === id) + 1} מתוך ${peers.length}`, `${kindName}, מהיקר לזול`));
    }
    const ri = lastIndex("rent", id);
    if (ri >= 0) {
      const rent = published("rent", id, "all", ri);
      stats.push(ppStat("שכר דירה ממוצע", money(rent), quarterLabel(DATA.periods[ri])));
      if (ri === i && rent) stats.push(ppStat("שנות שכירות", `${(price / (rent * 12)).toFixed(1)}`, "מחיר חלקי שכר דירה שנתי"));
    }
    for (let j = i; j >= 0; j--) {
      const f = loanFactor(state.track, state.years, j);
      const pj = published("sale", id, "all", j);
      if (f == null || pj == null) continue;
      stats.push(ppStat("החזר חודשי", money((pj * state.ltv) / 100 * f), `${state.ltv}% מימון, ${state.years} שנה, ${TRACKS[state.track].label}`));
      break;
    }
    const d = DATA.series.sale?.[id]?.all?.deals?.[i];
    if (d != null) stats.push(ppStat("עסקאות ברבעון", nf0.format(d), quarterLabel(DATA.periods[i])));
  } else {
    stats.push(ppStat("אין נתוני מחירים", "—"));
  }
  $("#pp-stats").innerHTML = stats.join("");

  // Rooms breakdown in the newest quarter with a sale price.
  const rooms = (DATA.rooms.sale || []).filter((r) => r !== "all");
  const ri = lastIndex("rent", id);
  const rows = rooms
    .map((r) => {
      const sp = i >= 0 ? published("sale", id, r, i) : null;
      const rp = ri >= 0 ? published("rent", id, r, ri) : null;
      if (sp == null && rp == null) return "";
      return `<tr><td>${ROOM_LABELS[r] || r}</td><td class="num">${millions(sp)}</td><td class="num">${money(rp)}</td></tr>`;
    })
    .join("");
  $("#pp-rooms").innerHTML = rows
    ? `<thead><tr><th scope="col">חדרים</th><th scope="col">מחיר ממוצע</th><th scope="col">שכר דירה</th></tr></thead><tbody>${rows}</tbody>`
    : "";

  const on = state.selected.includes(id);
  $("#pp-compare").textContent = on ? "הצגה בגרף ההשוואה" : "הוספה לגרף ההשוואה";
  $("#pp-compare").disabled = !on && state.selected.length >= MAX_COMPARE;
  renderPlaceChart(id);
}

function renderPlaceChart(id) {
  const c = ink();
  const pal = PALETTE[theme()];
  const lines = [[id, pal.series[0]]];
  if (id !== "n0") lines.push(["n0", pal.index]);
  charts.place.setOption(
    {
      backgroundColor: "transparent",
      grid: { left: 44, right: 12, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: c.secondary, fontSize: 11 }, itemWidth: 14, itemHeight: 6, icon: "roundRect" },
      tooltip: { trigger: "axis", valueFormatter: millions },
      xAxis: {
        type: "category",
        data: DATA.periods.map(shortQuarter),
        boundaryGap: false,
        axisLine: { lineStyle: { color: c.axis } },
        axisLabel: { color: c.muted, interval: 7, formatter: (v) => v.split(" ")[1] },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: c.muted, formatter: (v) => `${(v / 1e6).toFixed(1)}M` },
        splitLine: { lineStyle: { color: c.grid } },
      },
      series: lines.map(([pid, colour]) => ({
        name: PLACES[pid].name,
        type: "line",
        data: DATA.periods.map((_, i) => published("sale", pid, "all", i)),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2, color: colour, type: pid === id ? "solid" : "dashed" },
        itemStyle: { color: colour },
      })),
    },
    { notMerge: true },
  );
}

function compareFromPanel() {
  const id = state.place;
  if (!state.selected.includes(id)) {
    if (state.selected.length >= MAX_COMPARE) return;
    state.selected.push(id);
    slotFor(id);
  }
  closePlace();
  showTab("line");
  window.scrollTo({ top: $(".tabs").offsetTop - 8, behavior: "smooth" });
}

// Rows with data-id open the place panel, by click or keyboard.
function bindPlaceRows(tbody) {
  tbody.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) openPlace(row.dataset.id);
  });
  tbody.addEventListener("keydown", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openPlace(row.dataset.id);
    }
  });
}

// ---------- affordability calculator ----------

function loadCalc() {
  try {
    const saved = JSON.parse(localStorage.getItem("calc") || "{}");
    for (const key of Object.keys(CALC_DEFAULTS)) {
      if (saved[key] != null) state.calc[key] = saved[key];
    }
  } catch {}
  if (!TRACKS[state.calc.track]) state.calc.track = CALC_DEFAULTS.track;
  if (!(DATA.rooms.sale || []).includes(state.calc.rooms)) state.calc.rooms = "all";
}

function saveCalc() {
  try {
    localStorage.setItem("calc", JSON.stringify(state.calc));
  } catch {}
}

function fillCalc() {
  const c = state.calc;
  $("#calc-income").value = c.income;
  $("#calc-equity").value = c.equity;
  $("#calc-pti").value = c.pti;
  $("#calc-years").value = c.years;
  $("#calc-track").innerHTML = Object.entries(TRACKS)
    .map(([k, t]) => `<option value="${k}"${k === c.track ? " selected" : ""}>${t.label}</option>`)
    .join("");
  $("#calc-rooms").innerHTML = (DATA.rooms.sale || ["all"])
    .map((r) => `<option value="${r}"${r === c.rooms ? " selected" : ""}>${ROOM_LABELS[r] || r}</option>`)
    .join("");
}

function bindCalc() {
  const numbers = [
    ["#calc-income", "income", 0, 10_000_000],
    ["#calc-equity", "equity", 0, 1_000_000_000],
    ["#calc-pti", "pti", 5, 60],
    ["#calc-years", "years", 1, 40],
  ];
  for (const [sel, key, lo, hi] of numbers) {
    $(sel).addEventListener("input", (e) => {
      state.calc[key] = clampInput(e.target, lo, hi, state.calc[key]);
      saveCalc();
      renderCalc();
    });
  }
  for (const [sel, key] of [["#calc-track", "track"], ["#calc-rooms", "rooms"]]) {
    $(sel).addEventListener("change", (e) => {
      state.calc[key] = e.target.value;
      saveCalc();
      renderCalc();
    });
  }
}

// The newest quarter with prices and with rates for the chosen track.
function calcQuarter() {
  const c = state.calc;
  for (let i = DATA.periods.length - 1; i >= 0; i--) {
    if (loanFactor(c.track, c.years, i) != null && published("sale", "n0", c.rooms, i) != null) return i;
  }
  return -1;
}

function calcRows() {
  const c = state.calc;
  const i = calcQuarter();
  if (i < 0) return { i, rows: [] };
  const f = loanFactor(c.track, c.years, i);
  const budget = (c.income * c.pti) / 100;
  const rows = DATA.places
    .map((p) => {
      const price = published("sale", p.id, c.rooms, i);
      if (price == null) return null;
      const loan = Math.max(0, price - c.equity);
      const pay = loan * f;
      const missingEquity = Math.max(0, price * (1 - MAX_LTV / 100) - c.equity);
      const share = c.income > 0 ? (pay / c.income) * 100 : Infinity;
      return { p, price, pay, missingEquity, share, ok: missingEquity === 0 && pay <= budget };
    })
    .filter(Boolean)
    .sort((a, b) => a.price - b.price);
  return { i, f, budget, rows };
}

function renderCalc() {
  const c = state.calc;
  const { i, f, budget, rows } = calcRows();
  if (i < 0) {
    $("#calc-headline").innerHTML = "<p>אין מספיק נתונים לחישוב.</p>";
    $("#calc-body").innerHTML = "";
    return;
  }
  const byIncome = c.equity + budget / f;
  const byEquity = c.equity / (1 - MAX_LTV / 100);
  const max = Math.min(byIncome, byEquity);
  const reason =
    byIncome <= byEquity
      ? `ההחזר החודשי הוא המגבלה: ${c.pti}% מההכנסה הם ${money(budget)} בחודש, שמספיקים להלוואה של עד ${millions(budget / f)}.`
      : `ההון העצמי הוא המגבלה: במימון של עד ${MAX_LTV}%, הון עצמי של ${money(c.equity)} מספיק לדירה של עד ${millions(byEquity)}.`;
  const okCount = rows.filter((r) => r.ok).length;
  $("#calc-headline").innerHTML =
    `<p>אפשר לקנות דירה במחיר של עד</p><p class="big">${millions(max)}</p>` +
    `<p>${reason}</p>` +
    `<p>מחיר ממוצע בהישג יד ב-${okCount} מתוך ${rows.length} מקומות (${ROOM_LABELS[c.rooms]}, ${quarterLabel(DATA.periods[i])}), ` +
    `לפי הריבית הממוצעת באותו רבעון במסלול ${TRACKS[c.track].label}.</p>`;
  $("#calc-body").innerHTML = rows
    .map((r) => {
      const why = [];
      if (r.missingEquity > 0) why.push(`חסרים ${money(r.missingEquity)} הון עצמי`);
      if (r.pay > budget) why.push(Number.isFinite(r.share) ? `ההחזר ${Math.round(r.share)}% מההכנסה` : "אין הכנסה להחזר");
      const status = r.ok
        ? `<span class="ok">✓ בהישג יד</span>`
        : `<span class="no">✗ לא בהישג יד</span><span class="why">${why.join(" · ")}</span>`;
      return `<tr class="level-${r.p.level}" data-id="${r.p.id}" tabindex="0"><td>${r.p.name}</td><td class="num">${millions(r.price)}</td>` +
        `<td class="num">${r.pay > 0 ? money(r.pay) : "ללא משכנתא"}</td><td>${status}</td></tr>`;
    })
    .join("");
}

// ---------- theme ----------

function currentThemeChoice() {
  return document.documentElement.dataset.theme || "auto";
}

function applyThemeLabel() {
  const choice = currentThemeChoice();
  $("#theme").textContent = `תצוגה: ${THEMES[choice]}`;
  $("#theme").setAttribute("aria-label", `ערכת צבעים: ${THEMES[choice]}. לחיצה מחליפה`);
}

function cycleTheme() {
  const order = Object.keys(THEMES);
  const next = order[(order.indexOf(currentThemeChoice()) + 1) % order.length];
  if (next === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  try {
    if (next === "auto") localStorage.removeItem("theme");
    else localStorage.setItem("theme", next);
  } catch {}
  applyThemeLabel();
  rerenderAll();
}

function rerenderAll() {
  render();
  if (state.place) renderPlace();
}

// ---------- share link + CSV ----------

// The view is kept in the URL hash, so a copied link opens the same view.
function writeHash() {
  const params = new URLSearchParams({
    kind: state.kind,
    rooms: state.rooms,
    real: state.real,
    mode: state.mode,
    smooth: state.smooth ? "1" : "0",
    base: DATA.periods[state.base],
    tab: state.tab,
    sel: state.selected.join(","),
  });
  if (state.place) params.set("place", state.place);
  if (state.kind === "payment") {
    params.set("track", state.track);
    params.set("ltv", String(state.ltv));
    params.set("years", String(state.years));
  }
  // Without an explicit quarter the link follows the newest data.
  if (state.t !== DATA.periods.length - 1) params.set("t", DATA.periods[state.t]);
  history.replaceState(null, "", `#${params}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const pick = (key, allowed) => (allowed.includes(params.get(key)) ? params.get(key) : null);
  state.kind = pick("kind", hasRates() ? ["sale", "rent", "ratio", "payment"] : ["sale", "rent", "ratio"]) ?? state.kind;
  state.track = pick("track", Object.keys(TRACKS)) ?? state.track;
  const num = (key, lo, hi) => {
    const v = Number(params.get(key));
    return params.has(key) && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
  };
  state.ltv = num("ltv", 1, 100) ?? state.ltv;
  state.years = num("years", 1, 40) ?? state.years;
  state.real = pick("real", ["nominal", "real"]) ?? state.real;
  state.mode = pick("mode", ["price", "change"]) ?? state.mode;
  state.tab = pick("tab", hasRates() ? ["map", "line", "heat", "rates", "calc"] : ["map", "line", "heat"]) ?? state.tab;
  state.place = PLACES[params.get("place")] ? params.get("place") : null;
  state.smooth = params.get("smooth") === "1";
  if (params.get("rooms")) state.rooms = params.get("rooms");
  const base = DATA.periods.indexOf(params.get("base"));
  if (base >= 0) state.base = base;
  const t = DATA.periods.indexOf(params.get("t"));
  if (t >= 0) state.t = t;
  const sel = (params.get("sel") || "").split(",").filter((id) => PLACES[id]).slice(0, MAX_COMPARE);
  if (params.has("sel")) {
    state.selected = [];
    state.slots = {};
    for (const id of sel) {
      state.selected.push(id);
      slotFor(id);
    }
  }
}

async function shareLink() {
  writeHash();
  const button = $("#share");
  try {
    await navigator.clipboard.writeText(location.href);
    button.textContent = "הקישור הועתק ✓";
  } catch {
    window.prompt("העתיקו את הקישור:", location.href);
  }
  setTimeout(() => (button.textContent = "העתקת קישור לתצוגה"), 2000);
}

function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function download(name, lines) {
  // The BOM makes Excel open the Hebrew names as UTF-8.
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function downloadRatesCsv() {
  const codes = Object.keys(DATA.rates.series);
  const lines = [["month", ...codes].map(csvCell).join(",")];
  DATA.rates.months.forEach((m, i) => {
    lines.push([m, ...codes.map((c) => DATA.rates.series[c].values[i] ?? "")].map(csvCell).join(","));
  });
  download("mortgage-rates.csv", lines);
}

function downloadCalcCsv() {
  const { i, rows } = calcRows();
  const lines = [["place", "level", "quarter", "avg_price", "monthly_payment", "missing_equity", "payment_pct_of_income", "affordable"].join(",")];
  for (const r of rows) {
    const share = Number.isFinite(r.share) ? Math.round(r.share * 10) / 10 : "";
    lines.push([r.p.name, r.p.level, DATA.periods[i], Math.round(r.price), Math.round(r.pay), Math.round(r.missingEquity), share, r.ok ? "yes" : "no"].map(csvCell).join(","));
  }
  download("affordability.csv", lines);
}

// Everything the current options show, one row per place and quarter.
function downloadCsv() {
  if (state.tab === "rates") {
    downloadRatesCsv();
    return;
  }
  if (state.tab === "calc") {
    downloadCalcCsv();
    return;
  }
  const header = ["place", "level", "place_code", "quarter", valueName()];
  if (state.mode === "change") header[4] = `change_since_${DATA.periods[state.base]}_pct`;
  if (saleBased()) header.push("deals");
  const lines = [header.map(csvCell).join(",")];
  for (const p of placesWithData()) {
    DATA.periods.forEach((period, i) => {
      const v = value(p.id, i);
      if (v == null) return;
      const row = [p.name, p.level, p.code, period, Math.round(v * 100) / 100];
      if (saleBased()) row.push(deals(p.id, i) ?? "");
      lines.push(row.map(csvCell).join(","));
    });
  }
  const loan = state.kind === "payment" ? `${state.track}-ltv${state.ltv}-${state.years}y` : "";
  const parts = [state.kind, loan, state.rooms, state.real, state.mode, state.smooth ? "smoothed" : ""];
  download(`apartment-prices-${parts.filter(Boolean).join("-")}.csv`, lines);
}

// ---------- wiring ----------

function hasRates() {
  return Boolean(DATA?.rates?.months?.length);
}

function render() {
  writeHash();
  if (state.tab === "map") {
    renderMap();
    renderRanking();
    charts.map.resize();
  } else if (state.tab === "line") {
    renderPicker();
    renderLine();
    charts.line.resize();
  } else if (state.tab === "rates") {
    renderRates();
    charts.rates.resize();
  } else if (state.tab === "calc") {
    renderCalc();
  } else {
    renderHeat();
    charts.heat.resize();
  }
}

async function init() {
  const [data, geo] = await Promise.all([
    fetch("data/data.json").then((r) => r.json()),
    fetch("data/districts.geojson").then((r) => r.json()),
  ]);
  DATA = data;
  PLACES = Object.fromEntries(DATA.places.map((p) => [p.id, p]));
  echarts.registerMap("il", geo);

  state.t = DATA.periods.length - 1;
  state.base = 0;
  for (const id of ["n0", "c5000", "c3000", "c4000"]) {
    if (PLACES[id]) {
      state.selected.push(id);
      slotFor(id);
    }
  }
  // Older data files have no rates: hide what depends on them.
  $("#kind-payment").hidden = !hasRates();
  $("#tab-rates").hidden = !hasRates();
  $("#tab-calc").hidden = !hasRates();
  readHash();
  loadCalc();
  applyThemeLabel();
  renderKpis();

  const updated = new Date(DATA.generated_at);
  $("#updated").textContent = `עודכן ${updated.toLocaleDateString("he-IL")} · נתונים עד ${quarterLabel(DATA.periods.at(-1))}`;
  $("#notes").innerHTML = DATA.notes.map((n) => `<li>${n}</li>`).join("");
  const time = $("#time");
  time.max = DATA.periods.length - 1;
  time.value = state.t;

  setSegment("kind", state.kind);
  setSegment("real", state.real);
  setSegment("mode", state.mode);
  fillRooms();
  fillBase();
  fillTrack();
  fillCalc();
  syncControls();
  bindControls();
  bindCalc();
  bindPlaceRows($("#rank-body"));
  bindPlaceRows($("#calc-body"));
  $("#theme").addEventListener("click", cycleTheme);
  $("#pp-close").addEventListener("click", closePlace);
  $("#pp-compare").addEventListener("click", compareFromPanel);
  $("#pp-share").addEventListener("click", async () => {
    writeHash();
    try {
      await navigator.clipboard.writeText(location.href);
      $("#pp-share").textContent = "הקישור הועתק ✓";
    } catch {
      window.prompt("העתיקו את הקישור:", location.href);
    }
    setTimeout(() => ($("#pp-share").textContent = "העתקת קישור"), 2000);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.place) closePlace();
  });

  charts.map = echarts.init($("#map"));
  charts.line = echarts.init($("#line"));
  charts.heat = echarts.init($("#heat"));
  charts.rates = echarts.init($("#rates"));
  charts.map.on("click", (params) => {
    if (PLACES[params.name]) openPlace(params.name);
  });
  charts.heat.on("click", (params) => {
    const row = heatRows[params.value?.[1]];
    if (row) openPlace(row.id);
  });
  window.addEventListener("resize", () => Object.values(charts).forEach((ch) => ch.resize()));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerenderAll);

  showTab(state.tab);
  if (state.place) openPlace(state.place);
}

document.addEventListener("DOMContentLoaded", () => {
  init().catch((err) => {
    console.error(err);
    $("#updated").textContent = "טעינת הנתונים נכשלה.";
  });
});
