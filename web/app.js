"use strict";

// Apartment prices by district and big city over time (CBS data).
// Reads data/data.json (built by `python -m apartment_data.export.web`) and draws a map with a
// time slider, a ranking table, a line chart and a heatmap with ECharts.

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

const state = {
  kind: "sale", // 'sale', 'rent' or 'ratio' (price / yearly rent)
  rooms: "all",
  real: "nominal",
  mode: "price",
  smooth: false,
  base: 0,
  t: 0,
  tab: "map",
  selected: [],
  slots: {}, // place id -> palette slot; colour follows the place, not its position
};

let DATA = null;
let PLACES = {};
const charts = {};
let playTimer = null;

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

function formatAxis(v) {
  if (state.mode === "change") return `${Math.round(v)}%`;
  if (state.kind === "sale") return `${(v / 1e6).toFixed(1)}M`;
  if (state.kind === "ratio") return `${Math.round(v)}`;
  return nf0.format(v);
}

function valueName() {
  if (state.kind === "sale") return "מחיר ממוצע";
  if (state.kind === "rent") return "שכר דירה ממוצע";
  return "שנות שכירות";
}

function formatPercent(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function cell(placeId, kind = state.kind) {
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

// The level shown before the change transform: a price in NIS (nominal or real), or for
// 'ratio' the years of rent a dwelling costs (sale price / yearly rent).
function level(placeId, i) {
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
  return state.kind === "sale" ? (cell(placeId)?.deals?.[i] ?? null) : null;
}

function placesWithData() {
  return DATA.places.filter((p) => DATA.periods.some((_, i) => price(p.id, i) != null));
}

function roomsFor(kind) {
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
  $("#smooth").checked = state.smooth;
}

function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  });
  for (const name of ["map", "line", "heat"]) {
    $(`#panel-${name}`).hidden = name !== tab;
  }
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
  $("#rank-deals-head").hidden = state.kind !== "sale";
  $("#rank-body").innerHTML = rows
    .map(({ p, v, ch, d }) => {
      const second = state.mode === "change" ? formatPriceOnly(price(p.id, i)) : formatPercent(ch);
      const cls = ch == null ? "" : ch > 0 ? "up" : ch < 0 ? "down" : "";
      return `<tr class="level-${p.level}"><td>${placeLabel(p)}</td><td class="num">${formatValue(v)}</td>` +
        `<td class="num ${state.mode === "change" ? "" : cls}">${second}</td>` +
        (state.kind === "sale" ? `<td class="num">${d == null ? "—" : nf0.format(d)}</td>` : "") +
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
  // Without an explicit quarter the link follows the newest data.
  if (state.t !== DATA.periods.length - 1) params.set("t", DATA.periods[state.t]);
  history.replaceState(null, "", `#${params}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const pick = (key, allowed) => (allowed.includes(params.get(key)) ? params.get(key) : null);
  state.kind = pick("kind", ["sale", "rent", "ratio"]) ?? state.kind;
  state.real = pick("real", ["nominal", "real"]) ?? state.real;
  state.mode = pick("mode", ["price", "change"]) ?? state.mode;
  state.tab = pick("tab", ["map", "line", "heat"]) ?? state.tab;
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

// Everything the current options show, one row per place and quarter.
function downloadCsv() {
  const header = ["place", "level", "place_code", "quarter", valueName()];
  if (state.mode === "change") header[4] = `change_since_${DATA.periods[state.base]}_pct`;
  if (state.kind === "sale") header.push("deals");
  const lines = [header.map(csvCell).join(",")];
  for (const p of placesWithData()) {
    DATA.periods.forEach((period, i) => {
      const v = value(p.id, i);
      if (v == null) return;
      const row = [p.name, p.level, p.code, period, Math.round(v * 100) / 100];
      if (state.kind === "sale") row.push(deals(p.id, i) ?? "");
      lines.push(row.map(csvCell).join(","));
    });
  }
  const parts = [state.kind, state.rooms, state.real, state.mode, state.smooth ? "smoothed" : ""];
  const name = `apartment-prices-${parts.filter(Boolean).join("-")}.csv`;
  // The BOM makes Excel open the Hebrew names as UTF-8.
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- wiring ----------

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
  readHash();

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
  syncControls();
  bindControls();

  charts.map = echarts.init($("#map"));
  charts.line = echarts.init($("#line"));
  charts.heat = echarts.init($("#heat"));
  window.addEventListener("resize", () => Object.values(charts).forEach((ch) => ch.resize()));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);

  showTab(state.tab);
}

document.addEventListener("DOMContentLoaded", () => {
  init().catch((err) => {
    console.error(err);
    $("#updated").textContent = "טעינת הנתונים נכשלה.";
  });
});
