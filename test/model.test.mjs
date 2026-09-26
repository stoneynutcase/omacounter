// Model.js under node. The file has no Qt in it, so `require` loads the very
// file the shell runs rather than a copy that can drift.
import { test } from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const Model = require("../Model.js")

test("compact", () => {
  assert.equal(Model.compact(0), "0")
  assert.equal(Model.compact(999), "999")
  assert.equal(Model.compact(1000), "1K")
  assert.equal(Model.compact(1234), "1.2K")
  assert.equal(Model.compact(12345), "12.3K")
  assert.equal(Model.compact(123456), "123K")
  assert.equal(Model.compact(999950), "1M")
  assert.equal(Model.compact(1200000), "1.2M")
  assert.equal(Model.compact(2500000000), "2.5B")
  assert.equal(Model.compact(-1500), "-1.5K")
  assert.equal(Model.compact("nope"), "—")
})

test("grouped and display", () => {
  assert.equal(Model.grouped(1234567), "1,234,567")
  assert.equal(Model.grouped(12), "12")
  assert.equal(Model.display(12345, "long"), "12,345")
  assert.equal(Model.display(12345, "", "short"), "12.3K")
  assert.equal(Model.display(12345, "", "long"), "12,345")
  assert.equal(Model.display(null, "long"), "—")
})

test("odometer cells", () => {
  assert.deepEqual(Model.cells(1234), ["1", ",", "2", "3", "4"])
  assert.deepEqual(Model.cells(7), ["7"])
  assert.deepEqual(Model.cells(null), ["?"])
})

test("deltas", () => {
  assert.equal(Model.signed(12), "+12")
  assert.equal(Model.signed(-3), "−3")
  assert.equal(Model.signed(0), "±0")
  assert.equal(Model.deltaCaption({ deltaDay: 3, deltaWeek: 1200 }), "+3 today · +1,200 this week")
  assert.equal(Model.deltaCaption({ deltaDay: 0, deltaWeek: null }), "±0 today")
  assert.equal(Model.deltaCaption({ deltaDay: null, deltaWeek: null }), "")
})

test("time label", () => {
  assert.equal(Model.timeLabel("2026-09-21T15:04:05"), "15:04")
  assert.equal(Model.timeLabel(""), "")
})

test("bar items and tick", () => {
  const counters = [{ interval: 60 }, { interval: 3 }, {}]
  assert.equal(Model.barItems(counters, 0).length, 3)
  assert.equal(Model.barItems(counters, 2).length, 2)
  // A counter switched off the bar is skipped before the cap applies.
  assert.deepEqual(Model.barItems([{ bar: false, id: 1 }, { id: 2 }, { bar: true, id: 3 }], 0).map(c => c.id), [2, 3])
  assert.deepEqual(Model.barItems([{ bar: false, id: 1 }, { id: 2 }, { id: 3 }], 1).map(c => c.id), [2])
  assert.equal(Model.tickMinutes(counters, 15), 3)
  assert.equal(Model.tickMinutes([{ interval: 0.5 }], 15), 15)
  assert.equal(Model.tickMinutes([], "junk"), 15)
  // A report row's effective interval (raised to a rate cap) wins over what was configured.
  assert.equal(Model.tickMinutes([{ interval: 1, effectiveInterval: 5 }], 15), 5)
})

test("rate limit caption", () => {
  assert.equal(Model.rateLimitCaption({ rateLimited: false }), "")
  assert.equal(Model.rateLimitCaption({ rateLimited: true, fetchedAt: "2026-09-22T12:04:00", nextFetchAt: "2026-09-22T12:09:00" }), " · fetched 12:04, next 12:09")
  assert.equal(Model.rateLimitCaption({ rateLimited: true, fetchedAt: "", nextFetchAt: "2026-09-22T12:09:00" }), " · next 12:09")
})

test("retry caption", () => {
  assert.equal(Model.retryCaption({ error: "not found", nextFetchAt: "2026-09-22T12:09:00" }), " · retry 12:09")
  assert.equal(Model.retryCaption({ error: "not found", nextFetchAt: null }), "")
  assert.equal(Model.retryCaption({ error: null, nextFetchAt: "2026-09-22T12:09:00" }), "")
})

test("group rows", () => {
  const rows = [
    { group: "youtube", groupLabel: "YouTube" },
    { group: "github", groupLabel: "GitHub" },
    { group: "youtube", groupLabel: "YouTube" },
    { group: "", groupLabel: "" },
    { group: "github", groupLabel: "GitHub" }
  ]
  const groups = Model.groupRows(rows)
  assert.deepEqual(groups.map(g => [g.key, g.label, g.indices, g.offset]), [
    ["youtube", "YouTube", [0, 2], 0],
    ["github", "GitHub", [1, 4], 2],
    ["other", "Other", [3], 4]
  ])
  assert.deepEqual(Model.groupRows([]), [])
  assert.deepEqual(Model.groupRows(null), [])
})

test("ordering", () => {
  // Interleaved as configured; the panel (and the bar) show them grouped.
  const rows = [
    { id: "y1", group: "youtube" },
    { id: "g1", group: "github" },
    { id: "y2", group: "youtube" },
    { id: "m1", group: "mastodon" },
    { id: "g2", group: "github" }
  ]
  const ids = order => Model.permute(rows, order).map(r => r.id)
  assert.deepEqual(Model.panelOrder(rows), [0, 2, 1, 4, 3])
  assert.deepEqual(Model.inPanelOrder(rows).map(r => r.id), ["y1", "y2", "g1", "g2", "m1"])
  assert.deepEqual(Model.barItems(rows, 0).map(r => r.id), ["y1", "y2", "g1", "g2", "m1"])
  assert.deepEqual(Model.barItems(rows, 3).map(r => r.id), ["y1", "y2", "g1"])
  // Within a group: y2 up swaps the two YouTube rows; y1 up goes nowhere.
  assert.deepEqual(ids(Model.moveOrder(rows, 2, "up")), ["y2", "y1", "g1", "g2", "m1"])
  assert.equal(Model.moveOrder(rows, 0, "up"), null)
  assert.equal(Model.moveOrder(rows, 2, "down"), null)
  assert.deepEqual(ids(Model.moveOrder(rows, 4, "top")), ["y1", "y2", "g2", "g1", "m1"])
  assert.deepEqual(ids(Model.moveOrder(rows, 0, "bottom")), ["y2", "y1", "g1", "g2", "m1"])
  assert.equal(Model.moveOrder(rows, 9, "up"), null)
  // A position, as the drag computes it, clamped to the group.
  assert.deepEqual(ids(Model.moveOrder(rows, 0, 1)), ["y2", "y1", "g1", "g2", "m1"])
  assert.deepEqual(ids(Model.moveOrder(rows, 0, 7)), ["y2", "y1", "g1", "g2", "m1"])
  assert.equal(Model.moveOrder(rows, 0, 0), null)
  assert.deepEqual(ids(Model.moveGroupOrder(rows, "mastodon", 0)), ["m1", "y1", "y2", "g1", "g2"])
  assert.equal(Model.moveGroupOrder(rows, "mastodon", 2), null)
  // Whole groups.
  assert.deepEqual(ids(Model.moveGroupOrder(rows, "github", "up")), ["g1", "g2", "y1", "y2", "m1"])
  assert.deepEqual(ids(Model.moveGroupOrder(rows, "mastodon", "top")), ["m1", "y1", "y2", "g1", "g2"])
  assert.deepEqual(ids(Model.moveGroupOrder(rows, "youtube", "down")), ["g1", "g2", "y1", "y2", "m1"])
  assert.equal(Model.moveGroupOrder(rows, "youtube", "up"), null)
  assert.equal(Model.moveGroupOrder(rows, "mastodon", "bottom"), null)
  assert.equal(Model.moveGroupOrder(rows, "x", "up"), null)
  // Rows without a group share "other" and keep their order.
  assert.deepEqual(Model.panelOrder([{}, {}, {}]), [0, 1, 2])
  assert.deepEqual(Model.permute(["a", "b"], [1, 0, 5]), ["b", "a"])
})

test("clip", () => {
  assert.equal(Model.TOOLTIP_LABEL_MAX, 40)
  assert.equal(Model.clip("short"), "short")
  assert.equal(Model.clip("x".repeat(40)), "x".repeat(40))
  assert.equal(Model.clip("x".repeat(41)), "x".repeat(39) + "…")
  assert.equal(Model.clip("Syncing the Akai Sample with Your DAW in 2026", 20), "Syncing the Akai Sa…")
  assert.equal(Model.clip("a b c d e f g h i j k", 10), "a b c d e…")
  assert.equal(Model.clip(null), "")
  assert.equal(Model.entryTooltip({ label: "L".repeat(50), value: 1, unit: "x", error: null, deltaDay: null }), "L".repeat(39) + "…\n1 x")
})

test("tooltip and summary", () => {
  const counters = [
    { icon: "a", label: "Chan", value: 1234, unit: "subscribers", error: null, deltaDay: 4 },
    { icon: "b", label: "Vid", value: null, unit: "likes", error: "no key", deltaDay: null },
    { icon: "c", label: "Old", value: 10, unit: "likes", error: "quota", deltaDay: null }
  ]
  assert.equal(Model.tooltip(counters), "Chan: 1,234 subscribers\nVid: no key\nOld: 10 likes (stale: quota)")
  assert.equal(Model.entryTooltip(counters[0]), "Chan\n1,234 subscribers  ·  +4 today")
  assert.equal(Model.entryTooltip(counters[1]), "Vid\nno key")
  assert.equal(Model.entryTooltip(counters[2]), "Old\n10 likes\nstale: quota")
  assert.equal(Model.summary(counters), "a Chan: 1,234 (+4 today)\nb Vid: —\nc Old: 10")
  assert.match(Model.summary([]), /No counters yet/)
})
