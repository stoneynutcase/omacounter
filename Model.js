// Pure helpers shared by BarWidget.qml and Panel.qml. No Qt in here, so the
// same file runs under node for the tests (see test/model.test.mjs).

// 999 → "999", 1234 → "1.2K", 12345 → "12.3K", 123456 → "123K", 1200000 → "1.2M"
function compact(value) {
  var n = Number(value)
  if (!isFinite(n)) return "—"
  var sign = n < 0 ? "-" : ""
  n = Math.abs(n)
  if (n < 1000) return sign + String(Math.round(n))
  var units = [["B", 1e9], ["M", 1e6], ["K", 1e3]]
  for (var i = 0; i < units.length; i++) {
    var suffix = units[i][0], size = units[i][1]
    if (n >= size) {
      var scaled = n / size
      // One decimal until three digits would be needed anyway; then none.
      var text = scaled >= 100 ? String(Math.round(scaled)) : (Math.round(scaled * 10) / 10).toFixed(1)
      text = text.replace(/\.0$/, "")
      // 999.95K rounds up to "1000K"; promote instead.
      if (text === "1000" && i > 0) return sign + "1" + units[i - 1][0]
      return sign + text + suffix
    }
  }
  return sign + String(Math.round(n))
}

// 1234567 → "1,234,567"
function grouped(value) {
  var n = Number(value)
  if (!isFinite(n)) return "—"
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

// The bar face: "short" is compact, "long" is grouped. An unset style falls
// back to the widget's default.
function display(value, style, fallbackStyle) {
  if (value === null || value === undefined) return "—"
  var s = style || fallbackStyle || "short"
  return s === "long" ? grouped(value) : compact(value)
}

// Digit cells for the odometer: characters of the grouped number, where ","
// marks a narrow gap rather than a printed separator.
function cells(value) {
  if (value === null || value === undefined) return ["?"]
  return grouped(value).split("")
}

function signed(delta) {
  var n = Number(delta)
  if (!isFinite(n)) return ""
  if (n > 0) return "+" + grouped(n)
  if (n < 0) return "−" + grouped(-n)
  return "±0"
}

// "+3 today · +12 this week", "±0 today", or "" when there is no history yet.
function deltaCaption(counter) {
  if (!counter) return ""
  var parts = []
  if (counter.deltaDay !== null && counter.deltaDay !== undefined) parts.push(signed(counter.deltaDay) + " today")
  if (counter.deltaWeek !== null && counter.deltaWeek !== undefined) parts.push(signed(counter.deltaWeek) + " this week")
  return parts.join(" · ")
}

// "2026-09-21T15:04:05" → "15:04"
function timeLabel(iso) {
  var s = String(iso || "")
  var m = s.match(/T(\d{2}:\d{2})/)
  return m ? m[1] : ""
}

// Which counters the bar shows, in the panel's order: those not switched off
// the bar (`bar: false` keeps a counter panel-only), capped by maxItems
// (0 = all).
function barItems(counters, maxItems) {
  var list = inPanelOrder(counters)
  var shown = []
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].bar === false) continue
    shown.push(list[i])
  }
  var cap = Number(maxItems) > 0 ? Number(maxItems) : shown.length
  return shown.slice(0, cap)
}

// A tooltip's name line is cut here (a video title can run to a hundred
// characters); providers/base.py holds the same number for the CLI.
var TOOLTIP_LABEL_MAX = 40

// `text` cut to `limit` characters, an ellipsis counting as one.
function clip(text, limit) {
  var s = String(text === null || text === undefined ? "" : text)
  var n = limit === undefined ? TOOLTIP_LABEL_MAX : limit
  if (s.length <= n) return s
  return s.slice(0, Math.max(0, n - 1)).replace(/\s+$/, "") + "…"
}

// Tooltip: one line per counter with the exact number, in the panel's order.
function tooltip(counters) {
  var list = inPanelOrder(counters)
  var lines = []
  for (var i = 0; i < list.length; i++) {
    var c = list[i]
    if (c.error && (c.value === null || c.value === undefined)) lines.push(clip(c.label) + ": " + c.error)
    else lines.push(clip(c.label) + ": " + grouped(c.value) + (c.unit ? " " + c.unit : "") + (c.error ? " (stale: " + c.error + ")" : ""))
  }
  return lines.join("\n")
}

// Tooltip for one counter on the bar: its name (cut to TOOLTIP_LABEL_MAX),
// the exact number, and how it moved today when that is known. The CLI
// report carries a `tooltip` built by the counter's provider
// (providers/base.py default_tooltip is the Python twin of this); this is
// the fallback when that field is missing.
function entryTooltip(c) {
  if (!c) return ""
  if (c.error && (c.value === null || c.value === undefined)) return clip(c.label) + "\n" + c.error
  var line = grouped(c.value) + (c.unit ? " " + c.unit : "")
  if (c.deltaDay !== null && c.deltaDay !== undefined) line += "  ·  " + signed(c.deltaDay) + " today"
  if (c.error) line += "\nstale: " + c.error
  return clip(c.label) + "\n" + line
}

// How often the widget should run the CLI: the smallest interval any counter
// asks for, never below one minute. Report rows carry `effectiveInterval`
// (the configured interval raised to the provider's rate cap); configured
// counters only carry `interval`. The CLI decides per counter what is due.
function tickMinutes(counters, refreshMinutes) {
  var minutes = Math.max(1, Number(refreshMinutes) || 15)
  var list = Array.isArray(counters) ? counters : []
  for (var i = 0; i < list.length; i++) {
    var c = list[i] || {}
    var n = Number(c.effectiveInterval !== undefined && c.effectiveInterval !== null ? c.effectiveInterval : c.interval)
    if (isFinite(n) && n >= 1 && n < minutes) minutes = n
  }
  return minutes
}

// "just now", "5 minutes ago", "3 hours ago", "2 days ago": how long ago
// an ISO local timestamp was, as of `now` (milliseconds; defaults to the
// clock).
function ago(iso, now) {
  var t = Date.parse(String(iso || ""))
  if (isNaN(t)) return ""
  var seconds = Math.max(0, Math.round(((now === undefined ? Date.now() : now) - t) / 1000))
  if (seconds < 60) return "just now"
  var units = [["day", 86400], ["hour", 3600], ["minute", 60]]
  for (var i = 0; i < units.length; i++) {
    var n = Math.floor(seconds / units[i][1])
    if (n >= 1) return n + " " + units[i][0] + (n === 1 ? "" : "s") + " ago"
  }
  return "just now"
}

// " · fetched 5 minutes ago": a hard refresh landed inside the provider's
// rate cap, so the number shown is the cached one.
function rateLimitCaption(c, now) {
  if (!c || !c.rateLimited) return ""
  var when = ago(c.fetchedAt, now)
  return when ? " · fetched " + when : ""
}

// " · retry 12:09": when a failed counter is tried again.
function retryCaption(c) {
  if (!c || !c.error) return ""
  var next = timeLabel(c.nextFetchAt)
  return next ? " · retry " + next : ""
}

// The panel's sections: report rows grouped by their provider's group, in
// order of first appearance, each with the row indices it holds and the
// number of rows before it (for the flip-in stagger). Rows without a group
// (an unknown type) go under "Other".
function groupRows(counters) {
  var list = Array.isArray(counters) ? counters : []
  var groups = [], byKey = {}
  for (var i = 0; i < list.length; i++) {
    var c = list[i] || {}
    var key = c.group || "other"
    var g = byKey[key]
    if (!g) {
      g = { key: key, label: c.groupLabel || (key === "other" ? "Other" : key), indices: [], offset: 0 }
      byKey[key] = g
      groups.push(g)
    }
    g.indices.push(i)
  }
  var seen = 0
  for (var k = 0; k < groups.length; k++) {
    groups[k].offset = seen
    seen += groups[k].indices.length
  }
  return groups
}

// ---- ordering ---------------------------------------------------------------
// The one order everything shows: groups as the panel lists them, each
// group's counters in their configured order. The bar, the tooltip and the
// notification all follow it, so a counter added later still sits with its
// siblings, and moving a row or a section in the panel moves it everywhere.
//
// The helpers below return the new order as a list of old indices (a
// permutation over the rows given) or null when the move goes nowhere, so
// the caller can apply one permutation to the configured list and the
// fetched report alike. Rows carry `group` from the CLI report; configured
// counters do not, which is why the report is what gets permuted.
function orderOf(groups) {
  var out = []
  for (var k = 0; k < groups.length; k++) out = out.concat(groups[k].indices)
  return out
}

function panelOrder(counters) {
  return orderOf(groupRows(counters))
}

function permute(list, order) {
  var src = Array.isArray(list) ? list : []
  var out = []
  for (var i = 0; i < order.length; i++) if (order[i] < src.length) out.push(src[order[i]])
  return out
}

function inPanelOrder(counters) {
  return permute(counters, panelOrder(counters))
}

// Where an item at position `p` in a list of `n` goes for "up", "down",
// "top", "bottom", or a position given as a number (clamped); -1 when it
// is already there.
function movedPosition(p, n, where) {
  var q = p
  if (typeof where === "number") q = Math.max(0, Math.min(n - 1, Math.round(where)))
  else if (where === "up") q = p - 1
  else if (where === "down") q = p + 1
  else if (where === "top") q = 0
  else if (where === "bottom") q = n - 1
  if (q < 0 || q >= n || q === p) return -1
  return q
}

function shifted(list, p, q) {
  var out = list.slice()
  var item = out.splice(p, 1)[0]
  out.splice(q, 0, item)
  return out
}

// Move one counter within its group.
function moveOrder(counters, index, where) {
  var groups = groupRows(counters)
  for (var k = 0; k < groups.length; k++) {
    var p = groups[k].indices.indexOf(index)
    if (p < 0) continue
    var q = movedPosition(p, groups[k].indices.length, where)
    if (q < 0) return null
    groups[k].indices = shifted(groups[k].indices, p, q)
    return orderOf(groups)
  }
  return null
}

// Move a whole group (its section in the panel) among the groups.
function moveGroupOrder(counters, key, where) {
  var groups = groupRows(counters)
  for (var k = 0; k < groups.length; k++) {
    if (groups[k].key !== key) continue
    var q = movedPosition(k, groups.length, where)
    if (q < 0) return null
    return orderOf(shifted(groups, k, q))
  }
  return null
}

// Plain-text summary for the notification (right click on the bar).
function summary(counters) {
  var list = inPanelOrder(counters)
  if (list.length === 0) return "No counters yet — click the widget to add one."
  var lines = []
  for (var i = 0; i < list.length; i++) {
    var c = list[i]
    var line = c.icon + " " + clip(c.label) + ": " + (c.value === null || c.value === undefined ? "—" : grouped(c.value))
    if (c.deltaDay !== null && c.deltaDay !== undefined) line += " (" + signed(c.deltaDay) + " today)"
    lines.push(line)
  }
  return lines.join("\n")
}

if (typeof module !== "undefined") {
  module.exports = {
    compact: compact,
    grouped: grouped,
    display: display,
    cells: cells,
    signed: signed,
    deltaCaption: deltaCaption,
    timeLabel: timeLabel,
    clip: clip,
    TOOLTIP_LABEL_MAX: TOOLTIP_LABEL_MAX,
    barItems: barItems,
    tooltip: tooltip,
    entryTooltip: entryTooltip,
    tickMinutes: tickMinutes,
    ago: ago,
    rateLimitCaption: rateLimitCaption,
    retryCaption: retryCaption,
    groupRows: groupRows,
    panelOrder: panelOrder,
    permute: permute,
    inPanelOrder: inPanelOrder,
    moveOrder: moveOrder,
    moveGroupOrder: moveGroupOrder,
    summary: summary
  }
}
