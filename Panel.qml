pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The counters panel. Owns the fetch process and the refresh timer so the bar
// face stays current while the panel is closed. All numbers come from
// `bin/omacounter fetch` as JSON; this file only renders them.
Panel {
  id: root
  moduleName: "stoneynutcase.omacounter"
  ipcTarget: "stoneynutcase.omacounter"
  manageIpc: false

  property var anchorItem: null

  // The bar tracks the widget mounted in its slot (BarWidget.qml), not this
  // nested panel, so popout coordination identifies as that widget.
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  // ---- theme ----------------------------------------------------------------
  readonly property color fg: Color.popups.text
  readonly property color dim: Qt.darker(fg, 1.4)
  readonly property color dimmer: Qt.darker(fg, 1.55)
  readonly property color urgentColor: bar ? bar.urgent : Color.urgent
  readonly property string fontFam: bar ? bar.fontFamily : Style.font.family

  // A counter's `color` is a theme role or a hex value. Roles follow the theme
  // live; the bar face resolves against the bar palette, the panel against the
  // popup card, so the same token reads correctly on both surfaces.
  function colorFor(token, surfaceDefault) {
    var s = String(token || "").trim().toLowerCase()
    if (s === "" || s === "foreground" || s === "text") return surfaceDefault
    if (s === "accent") return Color.accent
    if (s === "urgent") return urgentColor
    if (s === "muted") return Color.muted
    if (s === "background") return Color.background
    var hex = Style.colorFromHex(s, null)
    return hex === null ? surfaceDefault : hex
  }

  // Glyph and number can be coloured apart. Per counter: `glyphColor` /
  // `textColor`, else `color` for both; then, for the glyph, the service's
  // brand colour the provider reports (YouTube red); then the widget's
  // defaults; then the surface foreground. Monochrome skips the per-counter
  // and brand colours: everything takes the widget's defaults, which are
  // the surface foreground unless set.
  function glyphColorFor(counter, surfaceDefault) {
    var token = counter && !monochrome ? (counter.glyphColor || counter.color || counter.brandColor) : ""
    return colorFor(token || defaultGlyphColor, surfaceDefault)
  }

  // In monochrome the number steps back a shade from the glyph, so the two
  // still read apart: the foreground mixed a third of the way toward the
  // surface it sits on, which holds on light themes as well as dark. A
  // widget textColor, being a choice, is used as given.
  function textColorFor(counter, surfaceDefault, surfaceBackground) {
    if (monochrome && !defaultTextColor) {
      var back = surfaceBackground !== undefined ? surfaceBackground : Color.popups.background
      return Qt.rgba(surfaceDefault.r + (back.r - surfaceDefault.r) * 0.35,
                     surfaceDefault.g + (back.g - surfaceDefault.g) * 0.35,
                     surfaceDefault.b + (back.b - surfaceDefault.b) * 0.35, 1)
    }
    var token = counter && !monochrome ? (counter.textColor || counter.color || counter.brandTextColor) : ""
    return colorFor(token || defaultTextColor, surfaceDefault)
  }

  // ---- paths ----------------------------------------------------------------
  readonly property string cliPath: decodeURIComponent(String(Qt.resolvedUrl("bin/omacounter")).replace(/^file:\/\//, ""))

  // ---- settings (inline on the shell.json entry) ----------------------------
  // Read from shell.json itself, with the injected `settings` as fallback.
  // The bar applies a changed entry to a running widget by patching its
  // layout in place, so the entry a re-mounted widget is handed after a
  // plugin reload is the one from before the patch: a counter removed
  // since the last shell start comes back. The file is what the shell
  // writes on every change, so it is the one copy that is never stale.
  readonly property string shellJsonPath: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy/shell.json"
  property var fileEntry: null
  readonly property var effectiveSettings: fileEntry || settings

  function setting(name, fallback) {
    var value = effectiveSettings ? effectiveSettings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function parseShellJson(raw) {
    try {
      var config = JSON.parse(String(raw || ""))
      var layout = config && config.bar && config.bar.layout ? config.bar.layout : {}
      var lists = [layout.left, layout.center, layout.right, config ? config.plugins : null]
      for (var l = 0; l < lists.length; l++) {
        var list = lists[l]
        if (!list || typeof list.length !== "number") continue
        for (var i = 0; i < list.length; i++) {
          var entry = list[i]
          if (entry && typeof entry === "object" && entry.id === root.moduleName) {
            fileEntry = entry
            return
          }
        }
      }
    } catch (e) {
      // Unparseable or half-written: keep whatever we had.
      return
    }
    fileEntry = null
  }

  FileView {
    id: shellJsonFile
    path: root.shellJsonPath
    watchChanges: true
    printErrors: false
    onLoaded: root.parseShellJson(text())
    onLoadFailed: root.fileEntry = null
    onFileChanged: reload()
  }

  // The first read can race shell startup; one delayed reload self-corrects.
  Timer {
    interval: 1500
    running: true
    onTriggered: shellJsonFile.reload()
  }

  readonly property int refreshMinutes: Math.max(1, parseInt(setting("refreshMinutes", 15), 10) || 15)
  readonly property string defaultStyle: String(setting("style", "short")) === "long" ? "long" : "short"
  readonly property string barMode: String(setting("barMode", "all")) === "cycle" ? "cycle" : "all"
  readonly property int cycleSeconds: Math.max(2, parseInt(setting("cycleSeconds", 5), 10) || 5)
  readonly property int maxBarItems: Math.max(0, parseInt(setting("maxBarItems", 0), 10) || 0)
  readonly property int barMaxWidth: Math.max(0, parseInt(setting("barMaxWidth", 480), 10) || 0)
  readonly property string defaultGlyphColor: String(setting("glyphColor", "") || "")
  readonly property string defaultTextColor: String(setting("textColor", "") || "")
  // A hand-edited file may hold the word rather than the boolean.
  readonly property bool monochrome: setting("monochrome", false) === true || String(setting("monochrome", "")).toLowerCase() === "true"
  // The list reaches the widget as a Qt list wrapper rather than a JS array
  // when the bar mounts it (Array.isArray says no, JSON.stringify says yes),
  // so it is normalised through a JSON round trip before anything reads it.
  readonly property var configuredCounters: {
    var list = setting("counters", [])
    if (!list || typeof list.length !== "number") return []
    var plain = Util.cloneJson(list)
    if (Array.isArray(plain)) return plain
    var out = []
    for (var i = 0; i < list.length; i++) out.push(Util.cloneJson(list[i]))
    return out
  }
  readonly property string countersJson: JSON.stringify(configuredCounters)

  // A changed counter list refetches (cache-gated, so an unchanged counter
  // costs nothing). Debounced: the host injects settings more than once.
  onCountersJsonChanged: scheduleRefresh(false)

  // ---- data -----------------------------------------------------------------
  property var report: null
  property string errorMessage: ""

  readonly property var counters: (report && Array.isArray(report.counters)) ? report.counters : []
  readonly property bool hasData: counters.length > 0
  readonly property bool configured: configuredCounters.length > 0
  readonly property string updatedText: report ? Model.timeLabel(report.generatedAt) : ""
  readonly property string tooltipText: Model.tooltip(counters)

  // Bar face entries, read by BarWidget.qml.
  property int cycleIndex: 0
  readonly property var barEntries: {
    var items = Model.barItems(counters, maxBarItems)
    if (barMode === "cycle" && items.length > 1) items = [items[cycleIndex % items.length]]
    var barFg = bar ? bar.barForeground : Color.foreground
    var barBg = bar ? bar.background : Color.background
    var out = []
    for (var i = 0; i < items.length; i++) {
      var c = items[i]
      out.push({
        icon: c.icon,
        text: Model.display(c.value, c.style, defaultStyle),
        label: c.label,
        exact: c.value === null || c.value === undefined ? "—" : Model.grouped(c.value) + (c.unit ? " " + c.unit : ""),
        iconColor: glyphColorFor(c, barFg),
        textColor: textColorFor(c, barFg, barBg),
        stale: !!c.error,
        // The provider owns its tooltip (via the CLI report); the JS
        // formatter is the fallback for a report from an older CLI.
        tooltip: c.tooltip || Model.entryTooltip(c)
      })
    }
    return out
  }

  Timer {
    interval: root.cycleSeconds * 1000
    running: root.barMode === "cycle" && Model.barItems(root.counters, root.maxBarItems).length > 1
    repeat: true
    onTriggered: root.cycleIndex = (root.cycleIndex + 1) % Math.max(1, Model.barItems(root.counters, root.maxBarItems).length)
  }

  // The card's full width (content plus padding and border), read by the bar
  // widget to place the anchor so the card's right edge sits on the widget's.
  readonly property real cardWidth: panel.contentWidth + panel.padding * 2 + Math.max(1, Style.space(2)) * 2

  // What the panel would like to be: header, list and footer end to end.
  // KeyboardPanel caps it to the screen; the list scrolls for the rest.
  readonly property real desiredHeight: hero.implicitHeight + heroSeparator.height + Style.space(12) * 2
    + (configured
       ? listColumn.implicitHeight + Style.space(12) * 2 + footerSeparator.height + footerRow.implicitHeight
       : emptyState.implicitHeight)

  // ---- open / close -----------------------------------------------------------
  // Bumped when the cards should reset to zero and count up again: the first
  // open of a session (nothing earlier to move from) and a hard refresh.
  // Every other open leaves the cards where they were, so only the digits
  // that changed since last time flip.
  property int resetSerial: 0
  property bool introPlayed: false
  onOpenedChanged: {
    if (opened && !introPlayed) {
      introPlayed = true
      resetSerial++
    }
  }

  // Hard refresh: every card back to zero, then refetch everything now.
  function hardRefresh() {
    resetSerial++
    refreshAll()
  }

  function open() {
    root.controller.show()
    refresh(false)
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  // A forced refetch on every bar instance, not just this one: the host
  // widget's broadcast() walks the copies of this widget on each monitor.
  function refreshAll() {
    if (hostWidget && typeof hostWidget.refreshAll === "function") hostWidget.refreshAll()
    else refresh(true)
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refreshAll() }
  }

  // ---- actions --------------------------------------------------------------
  function launchSetup() {
    if (!root.bar) return
    root.bar.run("omarchy-launch-floating-terminal-with-presentation " + Util.shellQuote(root.cliPath) + " setup")
  }

  function openCounter(counter) {
    // By absolute path: the shell's PATH is the session's, not ours.
    if (counter && counter.url) Util.execArgv(["/usr/bin/xdg-open", counter.url])
  }

  function notifySummary() {
    Util.execArgv(["omarchy-notification-send", "-g", "󰆙", "-u", "low", "Counters", Model.summary(root.counters)])
  }

  // Removal is a two-step: the row's button asks, the dialog confirms.
  property int pendingRemove: -1
  property string pendingRemoveLabel: ""

  function askRemove(index, label) {
    pendingRemoveLabel = String(label || "this counter")
    pendingRemove = index
  }

  function cancelRemove() {
    pendingRemove = -1
  }

  function confirmRemove() {
    var index = pendingRemove
    pendingRemove = -1
    if (index >= 0) removeCounter(index)
  }

  // The list an edit starts from. A save reaches shell.json at once but
  // comes back through the file watcher a moment later; until it does, the
  // list last saved is the truth, or a second click (hide two rows, move a
  // row twice) would start from the list before the first.
  property var localCounters: null
  readonly property var currentCounters: localCounters || configuredCounters
  onConfiguredCountersChanged: localCounters = null

  // Renaming: the row's pencil swaps its label for a field. Enter saves,
  // Escape cancels, focus leaving the field saves too; an empty name drops
  // the counter's own label so the resolved one (channel, repository, tag)
  // shows again. The key catcher stands aside while a field has focus.
  property int editingIndex: -1

  function startRename(index) {
    editingIndex = index
  }

  function cancelRename() {
    editingIndex = -1
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  function commitRename(index, text) {
    if (editingIndex !== index) return
    cancelRename()
    var label = String(text || "").trim()
    if (index < 0 || index >= currentCounters.length) return
    var current = String(currentCounters[index].label || "")
    if (label === current) return
    var next = []
    for (var i = 0; i < currentCounters.length; i++) {
      var c = Util.cloneJson(currentCounters[i])
      if (i === index) {
        if (label === "") delete c.label
        else c.label = label
      }
      next.push(c)
    }
    // The panel shows the new name at once; the refetch the save triggers
    // confirms it.
    if (report && counters[index]) {
      var updated = Util.cloneJson(report)
      var row = updated.counters[index]
      row.label = label || row.name || row.target
      report = updated
    }
    persistCounters(next)
  }

  // Show or hide one counter on the bar; it stays in the panel either way.
  // `bar: false` is stored, shown being the default is left out.
  function setOnBar(index, shown) {
    var next = []
    for (var i = 0; i < currentCounters.length; i++) {
      var c = Util.cloneJson(currentCounters[i])
      if (i === index) {
        if (shown) delete c.bar
        else c.bar = false
      }
      next.push(c)
    }
    persistCounters(next)
  }

  // Removing a counter rewrites the widget's own shell.json entry through the
  // shell, the same path `omarchy bar set` takes. The saved entry comes back
  // as new settings, which refetches (from cache) and redraws the bar.
  function removeCounter(index) {
    var next = []
    for (var i = 0; i < currentCounters.length; i++) if (i !== index) next.push(currentCounters[i])
    persistCounters(next)
  }

  // ---- reordering by drag -----------------------------------------------------
  // A row is dragged by its handle within its section, a section by the
  // handle on its title. While the pointer moves, a ghost follows it and a
  // line shows where it would land; the list itself does not change. On
  // release the move is worked out on the report rows (they know their
  // group), applied to the report, so the panel redraws at once, and the
  // same permutation is applied to the configured list and saved. Cards
  // snap to their new digits while this settles: a leaf falling from one
  // counter's number to another's would read as a change that never
  // happened.
  property bool reordering: false
  property int dragIndex: -1          // the counter being dragged, by its index
  property string dragGroup: ""       // the section being dragged, by group key
  readonly property bool dragging: dragIndex >= 0 || dragGroup !== ""
  property var dragBase: null         // the configured list when the drag began
  property real dragY: 0              // the ghost's top, in list coordinates
  property real dragGrab: 0           // how far below the ghost's top the pointer holds it

  Timer {
    id: reorderSettle
    interval: 400
    repeat: false
    onTriggered: root.reordering = false
  }

  // The report and the configured list must line up one to one for a
  // permutation of one to apply to the other; between a save and the next
  // report they can briefly differ, and then a drag does not start.
  readonly property bool orderable: {
    if (!hasData || counters.length !== currentCounters.length) return false
    for (var i = 0; i < counters.length; i++) {
      if (counters[i].index !== i || counters[i].type !== currentCounters[i].type) return false
    }
    return true
  }

  function beginDrag(y, grab) {
    dragBase = currentCounters
    dragGrab = grab
    dragY = y - grab
    reordering = true
    reorderSettle.stop()
  }

  function beginRowDrag(index, y, grab) {
    if (!orderable || dragging) return
    dragIndex = index
    beginDrag(y, grab)
  }

  function beginGroupDrag(key, y, grab) {
    if (!orderable || dragging || !key) return
    dragGroup = key
    beginDrag(y, grab)
  }

  // Reorder the report shown.
  function applyOrderToReport(order) {
    var rows = Model.permute(counters, order)
    for (var i = 0; i < rows.length; i++) {
      rows[i] = Util.cloneJson(rows[i])
      rows[i].index = i
    }
    var next = Util.cloneJson(report)
    next.counters = rows
    report = next
  }

  // Where the drop would land, worked out as the pointer moves and shown as
  // a line; nothing is reordered until the button is released.
  property int dropTarget: -1         // position within the section (row) or among sections (group)
  property bool dropShown: false      // whether the drop would move anything
  property real dropY: 0              // the line's y in list coordinates

  function itemTop(item) {
    return item.mapToItem(contentScroll.contentItem, 0, 0).y
  }

  // The row would go after every other row of its section whose centre is
  // above the ghost's centre. The line sits above the row now at that
  // position when moving up, below it when moving down.
  function dragRowTo(y) {
    if (dragIndex < 0) return
    dragY = y - dragGrab
    nudgeScroll(y)
    var centre = dragY + Style.space(46) / 2
    var groups = Model.groupRows(counters)
    for (var k = 0; k < groups.length; k++) {
      var p = groups[k].indices.indexOf(dragIndex)
      if (p < 0) continue
      var section = groupRepeater.itemAt(k)
      if (!section) return
      var target = 0
      for (var q = 0; q < groups[k].indices.length; q++) {
        if (q === p) continue
        var item = section.rows.itemAt(q)
        if (item && centre > itemTop(item) + item.height / 2) target++
      }
      showDrop(target, p, section.rows.itemAt(target), section.spacing)
      return
    }
  }

  // A section would go after every other section whose centre is above
  // the pointer.
  function dragGroupTo(y) {
    if (dragGroup === "") return
    dragY = y - dragGrab
    nudgeScroll(y)
    var groups = Model.groupRows(counters)
    var k = -1
    for (var i = 0; i < groups.length; i++) if (groups[i].key === dragGroup) k = i
    if (k < 0) return
    var target = 0
    for (var j = 0; j < groups.length; j++) {
      if (j === k) continue
      var section = groupRepeater.itemAt(j)
      if (section && y > itemTop(section) + section.height / 2) target++
    }
    showDrop(target, k, groupRepeater.itemAt(target), groupsColumn.spacing)
  }

  function showDrop(target, current, item, gap) {
    dropTarget = target
    dropShown = target !== current && !!item
    if (!dropShown) return
    var y = target < current ? itemTop(item) - gap / 2 : itemTop(item) + item.height + gap / 2
    // Above the first section or below the last, the gap is the list's
    // edge; keep the line inside the content or it is clipped away.
    dropY = Math.max(1, Math.min(contentScroll.contentHeight - 1, y))
  }

  // Dragging near the top or bottom of a list that scrolls moves it along.
  function nudgeScroll(y) {
    if (!contentScroll.interactive) return
    var edge = Style.space(28), step = Style.space(8)
    var seen = y - contentScroll.contentY
    var most = contentScroll.contentHeight - contentScroll.height
    if (seen < edge) contentScroll.contentY = Math.max(0, contentScroll.contentY - step)
    else if (seen > contentScroll.height - edge) contentScroll.contentY = Math.min(most, contentScroll.contentY + step)
  }

  // The drop: the move the line promised is applied to the report shown
  // (rows change place at once, cards snapping) and saved.
  function endDrag() {
    if (!dragging) return
    var order = null
    if (dropTarget >= 0) {
      if (dragIndex >= 0) order = Model.moveOrder(counters, dragIndex, dropTarget)
      else order = Model.moveGroupOrder(counters, dragGroup, dropTarget)
    }
    var base = dragBase
    dragIndex = -1
    dragGroup = ""
    dragBase = null
    dropTarget = -1
    dropShown = false
    reorderSettle.restart()
    if (order && base && order.length === base.length && order.length === counters.length) {
      applyOrderToReport(order)
      persistCounters(Model.permute(base, order))
    } else {
      scheduleRefresh(false)   // pick up a report that arrived mid-drag
    }
  }

  function persistCounters(next) {
    localCounters = next
    persistEntry({ counters: next })
  }

  // Monochrome from the hero button: the same setting the plugin's
  // settings page and `omarchy bar set … monochrome` write.
  function setMonochrome(on) {
    persistEntry({ monochrome: !!on })
  }

  // Rewrite the widget's own shell.json entry with `changes` applied,
  // through the shell, the same path `omarchy bar set` takes. The saved
  // entry comes back as new settings.
  function persistEntry(changes) {
    var entry = { id: root.moduleName }
    var base = root.effectiveSettings || {}
    for (var k in base) if (k !== "id") entry[k] = Util.cloneJson(base[k])
    for (var c in changes) entry[c] = changes[c]
    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget) root.hostWidget.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  // ---- fetch process --------------------------------------------------------
  // The exit code and the collected stdout arrive in either order, so a run is
  // final only once both are in. A refresh requested mid-run is queued once
  // (force wins), so a settings change during a poll re-runs with the new list.
  property bool collectorDone: true
  property bool processDone: true
  readonly property bool fetchBusy: !collectorDone || !processDone
  property string capturedText: ""
  property int exitCode: 0
  property bool sawExit: false
  property bool pendingRun: false
  property bool pendingForce: false
  property bool notInstalled: false

  function scheduleRefresh(force) {
    if (force) refreshDebounce.force = true
    refreshDebounce.restart()
  }

  Timer {
    id: refreshDebounce
    property bool force: false
    interval: 250
    repeat: false
    onTriggered: {
      var f = force
      force = false
      root.refresh(f)
    }
  }

  function refresh(force) {
    if (fetchProc.running) {
      pendingRun = true
      pendingForce = pendingForce || !!force
      return
    }
    collectorDone = false
    processDone = false
    capturedText = ""
    sawExit = false
    exitCode = 0
    var argv = [cliPath, "fetch", "--counters", countersJson, "--max-age", String(refreshMinutes)]
    if (force) argv.push("--force")
    // Through sh, so a missing interpreter is exit 127 rather than a failed
    // start that can take the shell down; the interpreter itself is the
    // system's python by absolute path, never whatever PATH would find.
    fetchProc.command = ["/bin/sh", "-c", 'exec /usr/bin/python3 "$@"', "sh"].concat(argv)
    fetchProc.running = true
  }

  // The CLI is started with the shell's environment cleared and only this
  // handed over: a fixed PATH, the locale, the home and XDG directories,
  // proxy settings, and the variables a credential may be given in. The
  // shell was started by a desktop session with whatever that session had
  // (a loader override, a PATH with a stranger's python first); none of it
  // reaches a process that handles an API key.
  readonly property var childEnv: buildChildEnv()

  function buildChildEnv() {
    var keep = [
      "HOME", "USER", "LANG", "LC_ALL",
      "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
      "http_proxy", "https_proxy", "all_proxy", "no_proxy",
      "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
      "OMARCHY_PATH",
      "YOUTUBE_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "GH_CONFIG_DIR", "GH_HOST"
    ]
    var env = { "PATH": "/usr/local/bin:/usr/bin:/bin" }
    for (var i = 0; i < keep.length; i++) {
      var value = Quickshell.env(keep[i])
      if (value) env[keep[i]] = String(value)
    }
    return env
  }

  function maybeFinalize() {
    if (!collectorDone || !processDone) return
    exitFallback.stop()
    finalizeRun()
  }

  function finalizeRun() {
    notInstalled = false
    var text = capturedText.trim()
    if (text === "") {
      if (!sawExit || exitCode === 126 || exitCode === 127) {
        notInstalled = true
        errorMessage = "omacounter could not start — is python3 installed and " + cliPath + " executable?"
      } else {
        errorMessage = "omacounter produced no output (exit " + exitCode + ")"
      }
    } else {
      try {
        var parsed = JSON.parse(text)
        if (parsed && Array.isArray(parsed.counters)) {
          // Not while a drag is in progress: the rows are in the order
          // being dragged into, and this report is in the saved one. The
          // drop refetches.
          if (!dragging) report = parsed
          errorMessage = ""
          if (cycleIndex >= parsed.counters.length) cycleIndex = 0
        } else {
          errorMessage = "malformed omacounter output"
        }
      } catch (e) {
        errorMessage = exitCode !== 0 ? "omacounter exited with code " + exitCode : "could not parse omacounter output"
      }
    }
    if (pendingRun) {
      var f = pendingForce
      pendingRun = false
      pendingForce = false
      Qt.callLater(function() { root.refresh(f) })
    }
  }

  Process {
    id: fetchProc
    clearEnvironment: true
    environment: root.childEnv
    onRunningChanged: {
      if (running) return
      root.processDone = true
      exitFallback.restart()
      root.maybeFinalize()
    }
    onExited: function(code) {
      root.sawExit = true
      root.exitCode = code
      root.processDone = true
      exitFallback.restart()
      root.maybeFinalize()
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.capturedText = text.length > 1024 * 1024 ? "" : text
        root.collectorDone = true
        root.maybeFinalize()
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var t = String(text || "").trim()
        if (t !== "" && root.capturedText.trim() === "") root.errorMessage = t.split("\n").pop()
      }
    }
  }

  Timer {
    id: exitFallback
    interval: 300
    repeat: false
    onTriggered: {
      root.collectorDone = true
      root.maybeFinalize()
    }
  }

  // Periodic refresh: the CLI decides per counter what is actually due. The
  // tick follows the report's effective intervals (a provider's rate cap
  // may raise a counter's), falling back to the configured ones.
  Timer {
    interval: Model.tickMinutes(root.hasData ? root.counters : root.configuredCounters, root.refreshMinutes) * 60 * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.scheduleRefresh(false)
  }

  // The moment a row says it is next due: a failed counter's retry (two
  // minutes on, or its rate cap), a rate-limited one's next slot, or an
  // ordinary counter's interval. One shot, re-armed on every report, so a
  // retry lands when the row says rather than on the next periodic tick.
  // Never sooner than a minute, the CLI's own floor, so a row whose time
  // is already past cannot spin this.
  Timer {
    id: dueTimer
    repeat: false
    onTriggered: root.scheduleRefresh(false)
  }

  onCountersChanged: armDueTimer()

  function armDueTimer() {
    var soonest = -1
    for (var i = 0; i < counters.length; i++) {
      var when = counters[i] ? counters[i].nextFetchAt : null
      if (!when) continue
      var t = Date.parse(String(when))   // "2026-09-22T18:48:00" is local time
      if (isNaN(t)) continue
      if (soonest < 0 || t < soonest) soonest = t
    }
    if (soonest < 0) {
      dueTimer.stop()
      return
    }
    dueTimer.interval = Math.max(60 * 1000, soonest - Date.now() + 2000)
    dueTimer.restart()
  }

  // ---- panel ----------------------------------------------------------------
  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(root.desiredHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // A rename field owns the keys while it is up.
      blocked: root.editingIndex >= 0
      // While the remove dialog is up, the keys belong to it: Esc cancels,
      // Enter takes the highlighted button, Tab and the arrows move it.
      onCloseRequested: {
        if (removeDialog.opened) root.cancelRemove()
        else root.close()
      }
      onActivateRequested: {
        if (!removeDialog.opened) return
        if (removeDialog.selectedIndex === 0) root.cancelRemove()
        else root.confirmRemove()
      }
      onReturnRequested: {
        if (!removeDialog.opened) return
        if (removeDialog.selectedIndex === 0) root.cancelRemove()
        else root.confirmRemove()
      }
      onTabRequested: function(direction) {
        if (removeDialog.opened) removeDialog.selectedIndex = removeDialog.selectedIndex === 0 ? 1 : 0
        else root.switchPanel(direction)
      }
      onTextKey: function(t) {
        if (removeDialog.opened) return
        if (t === "r" || t === "R") root.hardRefresh()
        else if (t === "a" || t === "A") root.launchSetup()
      }
      onMoveRequested: function(dx, dy) {
        if (removeDialog.opened) {
          if (dx !== 0) removeDialog.selectedIndex = removeDialog.selectedIndex === 0 ? 1 : 0
          return
        }
        if (dy !== 0 && contentScroll.interactive)
          contentScroll.contentY = Math.max(0, Math.min(contentScroll.contentHeight - contentScroll.height, contentScroll.contentY + dy * Style.space(50)))
      }

      // "Remove X from the bar?" over the whole panel, Cancel preselected
      // away from; the dialog's own buttons and the scrim answer by mouse.
      ConfirmDialog {
        id: removeDialog
        anchors.fill: parent
        z: 10
        opened: root.pendingRemove >= 0
        message: "Remove “" + root.pendingRemoveLabel + "” from the bar?"
        cancelText: "Keep"
        confirmText: "Remove"
        background: Color.popups.background
        foreground: root.fg
        fontFamily: root.fontFam
        onOpenedChanged: if (opened) selectedIndex = 0
        onCanceled: root.cancelRemove()
        onConfirmed: root.confirmRemove()
      }

      // Header and footer stay put; only the list between them scrolls.
      Column {
        id: contentColumn
        anchors.fill: parent
        spacing: Style.space(12)

          // ---- Hero
          PanelHero {
            id: hero
            title: "Counters"
            meta: root.updatedText !== ""
              ? "updated " + root.updatedText + (root.fetchBusy ? " · refreshing" : "")
              : (root.fetchBusy ? "fetching…" : "")
            foreground: root.fg
            fontFamily: root.fontFam
            iconComponent: Component {
              Text {
                textFormat: Text.PlainText
                text: "󰆙"
                color: root.fg
                font.family: root.fontFam
                font.pixelSize: Style.font.display
              }
            }
            trailingControl: Component {
              Row {
                spacing: Style.space(2)

                // Monochrome on or off; lit while on. The half circle is
                // the Nerd Font's own (nf-md-circle_half), so it sits level
                // with the refresh glyph at the same size.
                PanelActionButton {
                  iconText: "󱎕"
                  tooltipText: root.monochrome ? "Monochrome is on: click for the brand colours" : "Monochrome: every counter in the bar's own colour"
                  foreground: root.monochrome ? root.fg : root.dimmer
                  hoverColor: root.fg
                  fontFamily: root.fontFam
                  fontSize: Style.font.icon
                  onClicked: root.setMonochrome(!root.monochrome)
                }

                PanelActionButton {
                  iconText: "󰑐"
                  tooltipText: "Hard refresh: count up from zero (r)"
                  foreground: root.dimmer
                  hoverColor: root.fg
                  fontFamily: root.fontFam
                  fontSize: Style.font.icon
                  enabled: !root.fetchBusy
                  onClicked: root.hardRefresh()
                }
              }
            }
          }

          PanelSeparator { id: heroSeparator; foreground: root.fg }

          // ---- Empty state
          Column {
            id: emptyState
            visible: !root.configured
            width: parent.width
            spacing: Style.space(10)

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              text: "No counters yet. Add a YouTube channel's subscribers or a video's likes and watch the number tick up, like the hit counters of old."
              color: root.dim
              font.family: root.fontFam
              font.pixelSize: Style.font.bodySmall
            }

            Button {
              text: "Add a counter"
              iconText: "󰐕"
              bordered: true
              foreground: root.fg
              fontFamily: root.fontFam
              onClicked: root.launchSetup()
            }
          }

          // ---- The scrolling middle: the grouped rows and any error.
          // Sized to whatever the header and footer leave, with a scrollbar
          // when the rows outgrow it, so the footer never scrolls away.
          Flickable {
            id: contentScroll
            visible: root.configured
            width: parent.width
            height: Math.max(Style.space(46), contentColumn.height - hero.height - heroSeparator.height
                             - footerSeparator.height - footerRow.height - contentColumn.spacing * 4)
            contentWidth: width
            contentHeight: listColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            // Shown whenever the list overflows (Qt's default only appears
            // while scrolling, which hides that there is more to see).
            ScrollBar.vertical: ScrollBar {
              policy: contentScroll.contentHeight > contentScroll.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
            }

            // Where the drop would land: a line between two rows of the
            // section, or between two sections.
            Rectangle {
              visible: root.dragging && root.dropShown
              z: 6
              x: 0
              y: root.dropY - 1
              width: listColumn.width
              height: 2
              radius: 1
              color: Color.accent
            }

            // The ghost: the row or section title being dragged, riding
            // with the pointer above the list while its slot below shows
            // the faded placeholder.
            Rectangle {
              id: ghost
              visible: root.dragging
              z: 5
              x: 0
              y: root.dragY
              width: listColumn.width
              height: root.dragGroup !== "" ? ghostTitle.implicitHeight + Style.space(10) : Style.space(46)
              radius: Style.cornerRadius
              color: Color.popups.background
              border.width: 1
              border.color: Util.alpha(root.fg, 0.35)

              readonly property var counter: root.dragIndex >= 0 ? (root.counters[root.dragIndex] || ({})) : ({})
              readonly property string sectionLabel: {
                var groups = Model.groupRows(root.counters)
                for (var i = 0; i < groups.length; i++) if (groups[i].key === root.dragGroup) return groups[i].label
                return ""
              }

              Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: Style.hoverFillFor(root.fg, Color.accent)
              }

              // The handle: first for a row, after the title for a section.
              Text {
                x: root.dragGroup !== "" ? ghostTitle.x + ghostTitle.width + Style.space(6) : Style.space(6)
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(18)
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: "󰍜"
                color: root.fg
                font.family: root.fontFam
                font.pixelSize: Style.font.caption
              }

              // A section title
              PanelSectionHeader {
                id: ghostTitle
                visible: root.dragGroup !== ""
                x: Style.space(6)
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -topPadding / 2
                text: ghost.sectionLabel.toUpperCase()
                foreground: root.fg
                fontFamily: root.fontFam
              }

              // A row: glyph, label and the exact number
              Text {
                id: ghostIcon
                visible: root.dragIndex >= 0
                x: groupsColumn.actionsWidth
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: ghost.counter.icon || ""
                color: root.glyphColorFor(ghost.counter, root.fg)
                font.family: root.fontFam
                font.pixelSize: Style.font.iconLarge
              }

              Text {
                visible: root.dragIndex >= 0
                anchors.left: ghostIcon.right
                anchors.leftMargin: Style.space(10)
                anchors.right: ghostValue.left
                anchors.rightMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: ghost.counter.label || ""
                color: root.fg
                font.family: root.fontFam
                font.pixelSize: Style.font.body
                font.bold: true
              }

              Text {
                id: ghostValue
                visible: root.dragIndex >= 0
                anchors.right: parent.right
                anchors.rightMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: ghost.counter.value === null || ghost.counter.value === undefined ? "" : Model.grouped(ghost.counter.value)
                color: root.textColorFor(ghost.counter, root.fg)
                font.family: root.fontFam
                font.pixelSize: Style.font.body
                font.bold: true
              }
            }

            Column {
              id: listColumn
              // Leave the scrollbar its lane when it is showing, so the
              // remove buttons at the far right stay reachable.
              width: contentScroll.width - (contentScroll.contentHeight > contentScroll.height ? Style.space(10) : 0)
              spacing: Style.space(12)

          // ---- Counter rows, grouped by source
          Column {
            id: groupsColumn
            visible: root.hasData
            width: parent.width
            spacing: Style.space(10)

            // Sections in order of first appearance, each holding its
            // counters in configured order; the bar shows the same order.
            readonly property var groups: Model.groupRows(root.counters)

            // The room a hovered row makes at its start for its controls:
            // drag handle, rename, show/hide (remove sits at the far right).
            // Nothing is reserved at rest.
            readonly property real actionsWidth: Style.space(6) + Style.space(18) * 3 + Style.space(2) * 2 + Style.space(8)

            // A drag handle: the three bars, in the first place of the slot.
            // Press and move it and the row (or the section) follows the
            // pointer as a ghost while the list reorders underneath.
            component DragHandle: Item {
              id: handle
              property bool held: false
              property string tip: ""
              // Pointer position in list (Flickable content) coordinates,
              // and how far below the dragged item's top it took hold.
              signal grabbed(real y, real grab)
              signal moved(real y)
              signal dropped()

              readonly property bool hovered: handleMouse.containsMouse
              width: Style.space(18)
              height: Style.space(18)

              Text {
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: "󰍜"
                color: handle.hovered || handle.held ? root.fg : root.dimmer
                font.family: root.fontFam
                font.pixelSize: Style.font.caption
              }

              MouseArea {
                id: handleMouse
                anchors.fill: parent
                hoverEnabled: true
                // The list scrolls by drag too; this drag is ours.
                preventStealing: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                onPressed: function(mouse) {
                  var p = mapToItem(contentScroll.contentItem, mouse.x, mouse.y)
                  var top = handle.parent.mapToItem(contentScroll.contentItem, 0, 0).y
                  handle.grabbed(p.y, p.y - top)
                }
                onPositionChanged: function(mouse) {
                  if (pressed) handle.moved(mapToItem(contentScroll.contentItem, mouse.x, mouse.y).y)
                }
                onReleased: handle.dropped()
                onCanceled: handle.dropped()
              }

              PanelToolTip {
                visible: handle.tip !== "" && handle.hovered && !root.dragging
                text: handle.tip
                fontFamily: root.fontFam
              }
            }

            Repeater {
              id: groupRepeater
              model: groupsColumn.groups.length

              Column {
                id: section
                required property int index
                readonly property var group: groupsColumn.groups[index] || ({ key: "", label: "", indices: [], offset: 0 })
                readonly property Repeater rows: rowRepeater
                width: parent.width
                spacing: Style.space(4)
                // The section being dragged stays as a faded placeholder
                // under its ghost.
                opacity: root.dragGroup !== "" && root.dragGroup === group.key ? 0.3 : 1

                // The section header, with a drag handle in its slot: take
                // hold of it and the whole section moves among the others.
                Item {
                  id: header
                  visible: groupsColumn.groups.length > 1
                  width: parent.width
                  height: headerText.implicitHeight

                  readonly property bool hot: headerMouse.containsMouse || groupHandle.hovered || groupHandle.held

                  MouseArea {
                    id: headerMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                  }

                  PanelSectionHeader {
                    id: headerText
                    x: 0
                    width: Math.min(implicitWidth, parent.width - Style.space(18) - Style.space(8))
                    elide: Text.ElideRight
                    text: String(section.group.label || "").toUpperCase()
                    foreground: root.fg
                    fontFamily: root.fontFam
                  }

                  // The handle sits just after the title, so the title
                  // itself stays at the edge.
                  DragHandle {
                    id: groupHandle
                    visible: header.hot
                    held: root.dragGroup !== "" && root.dragGroup === section.group.key
                    tip: "Drag to move the " + section.group.label + " section"
                    anchors.left: headerText.right
                    anchors.leftMargin: Style.space(6)
                    anchors.verticalCenter: headerText.verticalCenter
                    anchors.verticalCenterOffset: headerText.topPadding / 2
                    onGrabbed: function(y, grab) { root.beginGroupDrag(section.group.key, y, grab) }
                    onMoved: function(y) { root.dragGroupTo(y) }
                    onDropped: root.endDrag()
                  }
                }

                // Rows are keyed by position within their group, not by the
                // report array, so a fresh fetch updates a row in place and
                // only the digits that changed flip.
                Repeater {
                  id: rowRepeater
                  model: section.group.indices.length

                  Item {
                    id: row
                    required property int index
                    // Position of this row within its group; the counter it shows
                    // is looked up through the group's index list, so a fetch
                    // updates the row in place while a regrouping rebuilds it.
                    readonly property int counterIndex: section.group.indices[index] !== undefined ? section.group.indices[index] : -1
                    readonly property int position: section.group.offset + index
                    readonly property var modelData: root.counters[counterIndex] || ({})
                    width: parent.width
                    height: Style.space(46)

                    readonly property color glyphColor: root.glyphColorFor(modelData, root.fg)
                    readonly property color textColor: root.textColorFor(modelData, root.fg)
                    readonly property bool hasValue: modelData.value !== null && modelData.value !== undefined
                    readonly property var digitCells: Model.cells(modelData.value)

                    Rectangle {
                      anchors.fill: parent
                      radius: Style.cornerRadius
                      color: rowMouse.containsMouse ? Style.hoverFillFor(root.fg, Color.accent) : "transparent"
                    }

                    MouseArea {
                      id: rowMouse
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: row.modelData.url && !row.editing ? Qt.PointingHandCursor : Qt.ArrowCursor
                      onClicked: if (!row.editing) root.openCounter(row.modelData)
                    }

                    // Row actions appear on hover: at the start, the content
                    // sliding right to make room, a drag handle (the row
                    // moves within its section only), rename and show/hide
                    // on the bar; at the far right, remove, which asks
                    // first. A row kept off the bar is dimmed.
                    readonly property bool onBar: modelData.bar !== false
                    readonly property bool held: root.dragIndex === counterIndex
                    readonly property bool editing: root.editingIndex === counterIndex
                    readonly property bool actionsHot: rowMouse.containsMouse || rowHandle.hovered || held || editing || renameButton.hot || barButton.hot || removeButton.hot
                    readonly property real actionsWidth: groupsColumn.actionsWidth
                    // The controls take no room at rest: the glyph and label
                    // slide right to make the slot while the row is hovered.
                    property real inset: actionsHot ? actionsWidth : Style.space(10)
                    Behavior on inset { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
                    // And the digits slide left for the remove button.
                    property real trail: actionsHot ? Style.space(6) + Style.space(18) + Style.space(8) : Style.space(10)
                    Behavior on trail { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
                    // The row being dragged stays as a faded placeholder
                    // under its ghost; a row kept off the bar is dimmed.
                    opacity: held ? 0.3 : (onBar ? 1 : 0.6)

                    DragHandle {
                      id: rowHandle
                      visible: row.actionsHot
                      held: row.held
                      tip: "Drag to reorder within " + section.group.label
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                      onGrabbed: function(y, grab) { root.beginRowDrag(row.counterIndex, y, grab) }
                      onMoved: function(y) { root.dragRowTo(y) }
                      onDropped: root.endDrag()
                    }

                    PanelActionButton {
                      id: renameButton
                      visible: row.actionsHot
                      property bool hot: false
                      anchors.left: rowHandle.right
                      anchors.leftMargin: Style.space(2)
                      anchors.verticalCenter: parent.verticalCenter
                      iconText: "󰏫"
                      tooltipText: "Rename (empty restores the default name)"
                      foreground: root.dimmer
                      hoverColor: root.fg
                      fontFamily: root.fontFam
                      fontSize: Style.font.caption
                      size: Style.space(18)
                      onHovered: function(h) { hot = h }
                      onClicked: root.startRename(row.counterIndex)
                    }

                    PanelActionButton {
                      id: barButton
                      visible: row.actionsHot
                      property bool hot: false
                      anchors.left: renameButton.right
                      anchors.leftMargin: Style.space(2)
                      anchors.verticalCenter: parent.verticalCenter
                      iconText: row.onBar ? "󰛐" : "󰛑"
                      tooltipText: row.onBar ? "Hide from the bar (stays in the panel)" : "Show on the bar"
                      foreground: row.onBar ? root.dimmer : Qt.darker(root.fg, 1.9)
                      hoverColor: root.fg
                      fontFamily: root.fontFam
                      fontSize: Style.font.caption
                      size: Style.space(18)
                      onHovered: function(h) { hot = h }
                      onClicked: root.setOnBar(row.counterIndex, !row.onBar)
                    }

                    // Remove sits alone at the far right, after the digits,
                    // which slide left to make its room while the row is
                    // hovered.
                    PanelActionButton {
                      id: removeButton
                      visible: row.actionsHot
                      property bool hot: false
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                      iconText: "󰅖"
                      tooltipText: "Remove this counter"
                      foreground: root.dimmer
                      hoverColor: root.urgentColor
                      fontFamily: root.fontFam
                      fontSize: Style.font.caption
                      size: Style.space(18)
                      onHovered: function(h) { hot = h }
                      onClicked: root.askRemove(row.counterIndex, row.modelData.label)
                    }

                    Text {
                      id: rowIcon
                      anchors.left: parent.left
                      anchors.leftMargin: row.inset
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: row.modelData.icon
                      color: row.glyphColor
                      font.family: root.fontFam
                      font.pixelSize: Style.font.iconLarge
                    }

                    Column {
                      anchors.left: rowIcon.right
                      anchors.leftMargin: Style.space(10)
                      anchors.right: digits.left
                      anchors.rightMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(2)

                      Text {
                        visible: !row.editing
                        width: parent.width
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        text: row.modelData.label
                        color: root.fg
                        font.family: root.fontFam
                        font.pixelSize: Style.font.body
                        font.bold: true
                      }

                      // The rename field, in the label's place while it
                      // is being edited.
                      TextField {
                        id: renameField
                        visible: row.editing
                        width: parent.width
                        placeholderText: String(row.modelData.name || row.modelData.target || "")
                        foreground: root.fg
                        font.family: root.fontFam
                        font.pixelSize: Style.font.body
                        font.bold: true
                        verticalPadding: Style.space(1)
                        horizontalPadding: Style.space(4)

                        readonly property bool editing: row.editing
                        onEditingChanged: {
                          if (!editing) return
                          // The counter's own label, not the resolved name:
                          // what would be saved, so clearing it reads right.
                          var own = root.currentCounters[row.counterIndex] ? String(root.currentCounters[row.counterIndex].label || "") : ""
                          text = own
                          Qt.callLater(function() {
                            renameField.forceActiveFocus()
                            renameField.selectAll()
                          })
                        }

                        Keys.onPressed: function(event) {
                          if (event.key === Qt.Key_Escape) {
                            root.cancelRename()
                            event.accepted = true
                          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            root.commitRename(row.counterIndex, text)
                            event.accepted = true
                          }
                        }

                        // Clicking away saves, like a file rename does.
                        onActiveFocusChanged: if (!activeFocus && row.editing) root.commitRename(row.counterIndex, text)
                      }

                      Text {
                        width: parent.width
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        text: row.modelData.error
                          ? (row.hasValue ? "stale · " : "") + row.modelData.error + Model.retryCaption(row.modelData)
                          : (Model.deltaCaption(row.modelData) || (row.modelData.unit ? row.modelData.unit : ""))
                            + (row.modelData.rateLimited ? Model.rateLimitCaption(row.modelData) : "")
                        color: row.modelData.error ? root.urgentColor : root.dimmer
                        font.family: root.fontFam
                        font.pixelSize: Style.font.caption
                      }
                    }

                    // The split-flap display at the far right: one card per
                    // digit, a narrow gap per thousand. Cards are keyed by
                    // position so a changed value flips the digits that
                    // changed instead of rebuilding.
                    Row {
                      id: digits
                      anchors.right: parent.right
                      anchors.rightMargin: row.trail
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(2)
                      opacity: row.modelData.error && row.hasValue ? 0.6 : 1

                      Repeater {
                        model: row.digitCells.length

                        FlipDigit {
                          id: cell
                          required property int index
                          digit: row.digitCells[index] || " "
                          color: row.hasValue ? row.textColor : root.dimmer
                          fontFamily: root.fontFam

                          // Leaves fall only while the panel is open, so a change
                          // fetched while it was closed is seen on the next open.
                          active: root.opened
                          // A row that is being moved shows its new number at
                          // once; the digits did not change, the row did.
                          snap: root.reordering

                          // Count up from zero, right to left like a counter
                          // spinning up: on the first open, on a hard refresh,
                          // and when a card is born into an already open panel
                          // (but not one re-created by a move).
                          readonly property int resetSerial: root.resetSerial
                          readonly property int stagger: (row.digitCells.length - 1 - index) * 40 + row.position * 120
                          onResetSerialChanged: flipIn(stagger)
                          Component.onCompleted: if (root.opened && !root.reordering) flipIn(stagger)
                        }
                      }
                    }
                  }
                }
              }
            }
          }

          // ---- Error
          Text {
            visible: root.errorMessage !== ""
            width: parent.width
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: root.errorMessage
            color: root.urgentColor
            font.family: root.fontFam
            font.pixelSize: Style.font.bodySmall
          }

            }
          }

          // ---- Footer
          PanelSeparator {
            id: footerSeparator
            visible: root.configured
            foreground: root.fg
          }

          Item {
            id: footerRow
            visible: root.configured
            width: parent.width
            implicitHeight: Math.max(footerHint.implicitHeight, addButton.implicitHeight)

            Text {
              id: footerHint
              anchors.left: parent.left
              anchors.right: addButton.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
              textFormat: Text.PlainText
              text: "click a row to open it · r hard refresh · a add"
              color: root.dimmer
              font.family: root.fontFam
              font.pixelSize: Style.font.caption
            }

            Button {
              id: addButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: "Add"
              iconText: "󰐕"
              bordered: true
              foreground: root.fg
              fontFamily: root.fontFam
              fontSize: Style.font.bodySmall
              horizontalPadding: Style.space(8)
              verticalPadding: Style.space(4)
              onClicked: root.launchSetup()
            }
          }
      }
    }
  }
}
